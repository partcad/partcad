# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "PartCAD"
copyright = "2024, PartCAD"
author = "PartCAD Inc."

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = []

templates_path = ["_templates"]
exclude_patterns = ["docs/build", "_build", ".git"]


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_logo = "images/logo.png"
html_js_files = [
    (
        "https://www.googletagmanager.com/gtag/js?id=G-PHMVTPEFBW",
        {"async": "async"},
    ),
    "js/analytics.js",
]


source_suffix = ".rst"
master_doc = "index"
html_title = "PartCAD Documentation"
html_show_copyright = False
html_show_sourcelink = False
html_show_sphinx = False
