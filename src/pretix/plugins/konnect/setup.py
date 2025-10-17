from setuptools import setup

setup(
    name='pretixkonnect',
    version='0.1.0',
    packages=['pretixkonnect'],  # your main plugin package
    install_requires=[],  # add dependencies if any
    entry_points={
        'pretix.plugin': [
            'pretixkonnect=pretixkonnect:PretixPluginMeta',
        ],
    },
)
