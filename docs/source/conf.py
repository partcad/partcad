# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "PartCAD"
copyright = "2024, PartCAD"
author = "PartCAD"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = []

templates_path = ["_templates"]
exclude_patterns = ["docs/build", "_build", ".git"]

# -- Internationalization (i18n) ---------------------------------------------
# English is the single source of truth. Translations live as gettext catalogs
# under docs/source/locales/<lang>/LC_MESSAGES/*.po and are regenerated with
# docs/update-translations.sh. On Read the Docs each language is a separate
# project that sets READTHEDOCS_LANGUAGE (de, es, ru, zh_CN); local builds
# default to English.
# Read the Docs sets READTHEDOCS_LANGUAGE from each translation project's
# language code (de, es, ru, and "zh-cn" for Simplified Chinese). Normalize the
# regional hyphen form to the gettext/sphinx-intl form ("zh-cn" -> "zh_CN") so
# the locales/ catalogs — and Chinese search word segmentation — are found.
_rtd_language = os.environ.get("READTHEDOCS_LANGUAGE", "en")
if "-" in _rtd_language:
    _base, _, _region = _rtd_language.partition("-")
    _rtd_language = f"{_base}_{_region.upper()}"
language = _rtd_language
locale_dirs = ["locales/"]
gettext_compact = False  # one .po per source file, easier to review and assign
# Do NOT add "literal-block" / "doctest-block" here: keeping the default ([])
# leaves code blocks, command examples, and CLI output untranslated, so the
# translated docs continue to document the English application interface.
gettext_additional_targets = []


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
