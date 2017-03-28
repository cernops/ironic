from ironic_lib import utils
from landbclient import client as landbclient
from oslo_concurrency import processutils

from ironic.conf import CONF
from oslo_log import log as logging
import re
import socket
import time


LOG = logging.getLogger(__name__)


class AIMSManager:

    @staticmethod
    def _get_kerberos_credentials():
        """Get kerberos token for svcironic

        Renews a kerberos token for svcironic account using keytab
        stored in /etc/svcbare.keytab
        """

        try:
            _, __ = utils.execute(
                "/usr/bin/kinit -kt /etc/svcbare.keytab svcbare",
                shell=True)
        except processutils.ProcessExecutionError:
            LOG.error("Authenticating as svcbare failed")
            raise

    @staticmethod
    def _remove_suffix(name):
        if name.endswith('.cern.ch'):
            return name[:-8]
        else:
            return name

    @staticmethod
    def _get_device_from_ip(addr):
        try:
            client_landb = landbclient.LanDB(username=CONF.cern.landb_username,
                                             password=CONF.cern.landb_password,
                                             host=CONF.cern.landb_hostname,
                                             port=CONF.cern.landb_port,
                                             protocol=CONF.cern.landb_protocol)

            name = client_landb.device_hostname(addr)[0]
            LOG.debug("Resolved {} to {}".format(addr, name))
            return name
        except Exception as e:
            LOG.error("Failed to resolve ip {}".format(addr))
            LOG.error(e)
            raise

    @staticmethod
    def register_node(node, image, mode):
        """Register node in AIMS

        Registers the node in AIMS in order to be able to perform PXE boot
        from the provided image.

        :param node: Ironic "node" object for the machine being registered
        :param image: Image from which the machine should be booted
        :param mode: One of {conductor|inspector} depending which service
        requests registration
        """

        # (makowals) This is ugly as hell but we need this till we develop
        # a nice decent way of detecting if LanDB has already synced
        time.sleep(15)

        LOG.debug("Starting AIMS registration for node {}".format(node.uuid))

        AIMSManager._get_kerberos_credentials()

        ip = node.driver_info['ipmi_address']
        hostname = AIMSManager._get_device_from_ip(ip)
        aims_base_command = "/usr/bin/aims2client addhost --hostname {} " \
            "--pxe --name {} ".format(hostname, image)

        try:
            if mode == "conductor":
                ironic_host = "{}:6385".format(
                    socket.gethostbyname(socket.gethostname()))
                command = "{} --kopts ipa-api-url=http://{}".format(
                    aims_base_command, ironic_host)

            elif mode == "inspector":
                ironic_host = "{}:5050/v1/continue".format(
                    socket.gethostbyname(socket.gethostname()))
                command = "{} --kopts ipa-inspection-callback-url=" \
                          "http://{}".format(aims_base_command, ironic_host)

            else:
                raise Exception("Wrong call-mode for AIMS")

            # utils.execute() does not throw exception if the command provided
            # fails, thus we manually check stderr for output indicating
            # something went wrong
            out, _e = utils.execute(command, shell=True)
            if "already in use by" in _e:
                # If MAC address already registered under another name, we need
                # to deregister the old first ...
                LOG.info("AIMS knows different name for {},"
                         " fixing ...".format(node.uuid))

                for line in _e.splitlines():
                    match = re.match(r"Hardware address for (?P<new_name>\S*) "
                                     r"already in use by (?P<old_name>\S*)",
                                     line)
                    if match:
                        old_hostname = match.group('old_name')
                        break

                fixcmd = "/usr/bin/aims2client remhost {}".format(old_hostname)
                utils.execute(fixcmd, shell=True)

                # ... and then retry again
                out, _e = utils.execute(command, shell=True)
                if "Error" in _e:
                    raise Exception(_e)
            elif "Cannot get device information for" in _e \
                 or "is not registered with aims2" in _e:
                # This means we have a race condition and LanDB returned us
                # an old hostname, but the device has already been renamed.
                # We need to wait a moment and try again. This issue has been
                # observed when deleting an instances with nova-landb-rename
                # implemented. Did not happen when creating new instances.
                for attempt in range(0, int(CONF.cern.aims_attempts)):
                    LOG.info("AIMS race detected for {}".format(hostname))

                    time.sleep(int(CONF.cern.aims_waittime))

                    new_hostname = AIMSManager._get_device_from_ip(ip)
                    if new_hostname == hostname:
                        # Race not resolved, still getting wrong name, wait...
                        continue
                    LOG.info("AIMS race resolved between {} and "
                             "{}. Retrying.".format(hostname, new_hostname))
                    command.replace(hostname, new_hostname)

                    out, _e = utils.execute(command, shell=True)

                    if "Error" in _e:
                        raise Exception(_e)
                    else:
                        # Escape from for-loop
                        break
            elif "Error" in _e:
                raise Exception(_e)
            LOG.debug(out)

            # before proceeding make sure node PXE status is synced
            AIMSManager.wait_for_ready(hostname,
                                       attempts=int(CONF.cern.aims_attempts),
                                       waittime=int(CONF.cern.aims_waittime))

        except Exception as e:
            LOG.error("AIMS registration failed for node"
                      " {} ({} {})".format(node.uuid, ip, hostname))
            LOG.error(e)
            raise

        LOG.info("Finished AIMS registration for node"
                 " {} ({} {})".format(node.uuid, ip, hostname))

    @staticmethod
    def deregister_node(node):
        """Deregister node in AIMS

        Removes node from AIMS in order to allow boot from local disk.

        Please note this method is not currently uses as this part is
        performed by Ironic Python Agent (using HTTP GET request sent directly
        from the affected machine).

        :param node: Hostname of the machine to be removed from AIMS
        """

        LOG.debug("Starting AIMS deregistration for node %s".format(node.uuid))

        AIMSManager._get_kerberos_credentials()

        try:
            # utils.execute() does not throw exception if the command provided
            # fails, thus we manually check stderr for output indicating
            # something went wrong
            out, _e = utils.execute("/usr/bin/aims2client pxeoff " +
                                    AIMSManager._remove_suffix(node),
                                    shell=False)

            if "Error" in _e:
                raise Exception(_e)
            LOG.debug(out)

        except Exception as e:
            LOG.error("AIMS dereg failed for node %s".format(node.uuid))
            LOG.error(e)
            raise

        LOG.debug("Finished AIMS dereg for node %s".format(node.uuid))

    @staticmethod
    def wait_for_ready(node, attempts=12, waittime=10):
        """
        Waits a given number of attempts for the sync state to be
        correct with a wait time in between.
        """

        for attempt in range(0, attempts):
            command = "/usr/bin/aims2client showhost {} --all".format(
                AIMSManager._remove_suffix(node))

            # utils.execute() does not throw exception if the command provided
            # fails, thus we manually check stderr for output indicating
            # something went wrong
            out, _e = utils.execute(command, shell=True)
            if "Error" in _e:
                raise Exception(_e)
            LOG.debug(out)

            statuses = []
            for line in out.splitlines():
                match = re.match(r"^PXE boot synced:\s+(?P<status>[yYnN])",
                                 line)
                if match:
                    LOG.debug("Found a boot synced statement (%s)" % line)
                    statuses.append(match.group('status'))

            if re.match(r"^[yY]+$", "".join(statuses)):
                LOG.debug(
                    "Sync status for '%s' is set to Y on all interfaces"
                    % node)
                return
            else:
                LOG.debug("Sync status is not Y for all interfaces")
                LOG.debug("Sleeping for %d seconds..." % waittime)
                time.sleep(waittime)

        LOG.error(out.strip())
        raise Exception("Sync status is not Y for '%s'" % node)
