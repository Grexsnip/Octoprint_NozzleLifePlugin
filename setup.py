from setuptools import setup

plugin_identifier = "nozzlelifetracker"
plugin_package = "octoprint_nozzlelifetracker"
plugin_name = "Nozzle Life Tracker"
plugin_version = "0.2.7"
plugin_description = "Tracks nozzle usage time and displays wear status."
plugin_author = "Andy Rabin"
plugin_author_email = "andy.rabin@gmail.com"
plugin_url = "https://github.com/Grexsnip/OctoPrint-NozzleLifeTracker"
plugin_license = "AGPLv3"

setup(
    name=plugin_name,
    version=plugin_version,
    description=plugin_description,
    author=plugin_author,
    author_email=plugin_author_email,
    url=plugin_url,
    license=plugin_license,
    packages=find_packages(exclude=("tests", "dev*", "build*", "dist*")),
    package_data={
        plugin_package: [
            "plugin.yaml",
            "templates/*.jinja2",
            "templates/settings/*.jinja2",
            "templates/sidebar/*.jinja2",
            "static/js/*.js",
            "static/css/*.css",
            "static/less/*.less",
            "translations/*.*",
        ]
    },
    include_package_data=True,
    zip_safe=False,
    install_requires=[],
    python_requires=">=3.8,<3.12",
    entry_points={
        "octoprint.plugin": [
            f"{plugin_identifier} = {plugin_package}"
        ]
    },
)
