"""
wagtail_hooks.py — Wire up the SnippetViewSetGroup
"""
from wagtail.snippets.models import register_snippet
from .snippets import ListedCompaniesGroup

register_snippet(ListedCompaniesGroup)
