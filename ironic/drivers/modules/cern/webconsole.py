from ironic_lib import metrics_utils
from ironic.common import exception
from ironic.drivers import base
from ironic.drivers.modules import ipmitool

METRICS = metrics_utils.get_metrics_logger(__name__)


class CernWebConsole(base.ConsoleInterface):
    """A ConsoleInterface that returns BMC URL and credentials."""

    def get_properties(self):
        return {
            'ipmi_address': "IP address or hostname of the node.",
            'ipmi_password': "password.",
            'ipmi_username': "username.",
        }

    def start_console(self, task):
        pass

    def stop_console(self, task):
        pass

    @METRICS.timer('CernWebConsole.get_console')
    def get_console(self, task):
        """Get the type and connection information about the console."""
        driver_info = ipmitool._parse_driver_info(task.node)
        url = "https://" + task.node.name + "-ipmi.cern.ch"
        username = driver_info['username']
        password = driver_info['password']
        return {'url': url,
                'username': username,
                'password': password}

    @METRICS.timer('CernWebConsole.validate')
    def validate(self, task):
        """Validate the Node console info."""

        driver_info = ipmitool._parse_driver_info(task.node)
        if not driver_info['username']:
            raise exception.MissingParameterValue(
                "Missing 'username' parameter in node's driver_info.")

        if not driver_info['password']:
            raise exception.MissingParameterValue(
                "Missing 'password' parameter in node's driver_info.")
