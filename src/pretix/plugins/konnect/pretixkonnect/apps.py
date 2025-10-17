try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")

from django.utils.translation import gettext_lazy as _

class PluginApp(PluginConfig):
    name = 'pretixkonnect'
    verbose_name = _('Konnect Payment')

    class PretixPluginMeta:
        name = _('Konnect Payment')
        author = _('Ala')  # your name
        version = '1.0.0'
        category = 'PAYMENT'
        #picture = 'pretixkonnect/konnect_logo.svg'  # optional static logo path
        visible = True
        featured = False
        restricted = False
        description = _("Integrate Konnect as a payment option in pretix.")
        compatibility = 'pretix>=2.7.0'  # your version info
        settings_links = [
            ((_("Konnect Settings"),), "pretixkonnect:konnect_settings", {}),
        ]
        navigation_links = [
            ((_("Konnect Payment"),), "pretixkonnect:konnect_settings", {}),
        ]


    def ready(self):
        from . import signals  # ensures your signals are registered
