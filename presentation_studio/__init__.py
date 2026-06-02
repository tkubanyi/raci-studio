"""Local Presentation Studio — brand PPTX generation from documents with AI assist."""

from presentation_studio.config import PresentationSettings, get_settings
from presentation_studio.content_parser import load_source
from presentation_studio.deck_builder import build_deck

__all__ = ["PresentationSettings", "get_settings", "load_source", "build_deck"]
