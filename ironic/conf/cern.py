from oslo_config import cfg

opts = [
    cfg.StrOpt('deploy_image_name',
               default='', secret=True,
               help='deploy image name'),
    cfg.StrOpt('landb_username',
               default='', secret=True,
               help='landb username'),
    cfg.StrOpt('landb_password',
               default='', secret=True,
               help='landb password'),
    cfg.StrOpt('landb_hostname',
               default='', secret=True,
               help='landb hostname'),
    cfg.StrOpt('landb_port',
               default='443', secret=True,
               help='landb port'),
    cfg.StrOpt('landb_protocol',
               default='https', secret=True,
               help='landb protocol'),
    cfg.StrOpt('aims_waittime',
               default='https', secret=True,
               help='aims waittime'),
    cfg.StrOpt('aims_attempts',
               default='https', secret=True,
               help='aims attempts'),
]


def register_opts(conf):
    conf.register_opts(opts, group='cern')
