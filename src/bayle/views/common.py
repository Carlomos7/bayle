"""The words every client shows when the launcher must ask or refuse: one schema for all presenters (Qt-free, frozen,
JSON-clean through prompt_dict). A Confirm asks before a change, a Pick asks which rows of a list, a Choose asks which
way to go (named verbs), a Refusal says why something cannot go ahead. The strings are final (tr() already applied)."""

from bayle.work.prompts import Choice, Choose, Confirm, Pick, Prompt, Refusal, prompt_dict

__all__ = ["Choice", "Choose", "Confirm", "Pick", "Prompt", "Refusal", "prompt_dict"]
