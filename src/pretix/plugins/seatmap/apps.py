from django.utils.translation import gettext_lazy as _

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")


__version__ = "1.0.0"


class PluginApp(PluginConfig):
    default = True
    name = "pretix.plugins.seatmap"
    verbose_name = _("Seat maps")

    class PretixPluginMeta:
        name = _("Seat maps")
        author = _("You")
        description = _("Manually assign seats to attendees.")
        visible = True
        version = __version__
        category = "CUSTOMIZATION"
        compatibility = "pretix>=2023.1.0"

    def ready(self):
        from . import signals  # NOQA
