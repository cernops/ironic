from ironic_lib import metrics_utils
from ironic.conductor import task_manager
from ironic.drivers.modules import ipmitool

METRICS = metrics_utils.get_metrics_logger(__name__)


class CernIPMIManagement(ipmitool.IPMIManagement):
    @METRICS.timer('CernIPMIManagement.set_boot_device')
    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for the task's node.

        Overrides the parent class call always using persistent=False,
        as in CERN deployment we always want to first boot from network and
        only afterwards from the local drive.

        """
        super(CernIPMIManagement, self).set_boot_device(task, device, False)
