"""Game types: pure functions over a JSON-serialisable state.

A game type never touches the database or the network. The service layer
(play.services) loads the room, checks who is acting, calls the game type,
and stores the result in one transaction.
"""

import random


class ActionInvalid(Exception):
    """The action isn't allowed in the current state, or its input is bad."""


class CardSource:
    """Cards available to a deck: `all()` for building one, `get(key)` to
    show one. Tests pass a plain list; the service passes a database-backed
    source (play.cards.DatabaseCards)."""

    def __init__(self, cards):
        self._cards = list(cards)
        self._by_key = {card["key"]: card for card in self._cards}

    def all(self):
        return self._cards

    def get(self, key):
        return self._by_key.get(key)


def as_source(cards):
    return cards if hasattr(cards, "get") and hasattr(cards, "all") else CardSource(cards)


def new_seed():
    return random.SystemRandom().randrange(1, 10**9)


class QuestionsGame:
    """A shared shuffled deck: Next shows the next card, Reset reshuffles.
    Covers today's modes (questions, truth, challenge, spicy, mixed, would)."""

    key = "questions"

    def start(self, cards, seed):
        source = as_source(cards)
        deck = [card["key"] for card in source.all()]
        random.Random(seed).shuffle(deck)
        return {
            "deck": deck,
            "position": 0,
            "seed": seed,
            "finished": not deck,
            "current": self._card(source, deck[0]) if deck else None,
        }

    def apply(self, state, action, actor_slot, cards, payload=None, seed=None):
        if action == "next":
            return self._next(state, cards)
        if action == "reset":
            return self.start(cards, seed if seed is not None else new_seed())
        raise ActionInvalid("Unknown action.")

    def insert_card(self, state, card, seed):
        """Add a new card at a random position after the current one, once."""
        if card["key"] in state["deck"]:
            return state
        deck = list(state["deck"])
        start = min(state["position"] + 1, len(deck))
        deck.insert(random.Random(seed).randint(start, len(deck)), card["key"])
        new = dict(state, deck=deck)
        if state["finished"]:
            new.update(finished=False, current=card, position=deck.index(card["key"]))
        return new

    def view(self, state, viewer_slot):
        """What a player may see. The deck order stays on the server."""
        total = len(state["deck"])
        return {
            "current": state["current"],
            "position": state["position"],
            "remaining": max(total - state["position"] - 1, 0),
            "total": total,
            "finished": state["finished"],
        }

    def _next(self, state, cards):
        if state["finished"]:
            raise ActionInvalid("There are no more cards. Reset to start again.")
        position = state["position"] + 1
        new = dict(state, position=position)
        if position >= len(state["deck"]):
            new.update(finished=True, current=None)
        else:
            new["current"] = self._card(as_source(cards), state["deck"][position])
        return new

    @staticmethod
    def _card(source, key):
        # A card deleted after the deck was built still shows something.
        return source.get(key) or {"key": key, "text": "(This question was removed.)", "mode": "", "custom": False}


class AnswerRevealGame(QuestionsGame):
    """Both partners answer the same card privately; neither answer is shown
    to the other until both have answered. Then Next moves on."""

    key = "answer_reveal"
    MAX_ANSWER = 500

    def start(self, cards, seed):
        return dict(super().start(cards, seed), phase="answering", answers={})

    def apply(self, state, action, actor_slot, cards, payload=None, seed=None):
        if action == "answer":
            return self._answer(state, actor_slot, payload or {})
        if action == "next":
            if state["phase"] != "revealed":
                raise ActionInvalid("Both of you answer first.")
            return dict(super()._next(state, cards), phase="answering", answers={})
        return super().apply(state, action, actor_slot, cards, payload, seed)

    def view(self, state, viewer_slot):
        mine, theirs = str(viewer_slot), str(3 - viewer_slot)
        revealed = state["phase"] == "revealed"
        return dict(
            super().view(state, viewer_slot),
            phase=state["phase"],
            my_answer=state["answers"].get(mine),
            partner_answered=theirs in state["answers"],
            # Only once both have answered; before that it is never sent.
            partner_answer=state["answers"].get(theirs) if revealed else None,
        )

    def _answer(self, state, actor_slot, payload):
        if state["phase"] != "answering" or state["finished"]:
            raise ActionInvalid("Answers are already revealed.")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > self.MAX_ANSWER:
            raise ActionInvalid(f"Answers need 1 to {self.MAX_ANSWER} characters.")
        answers = dict(state["answers"], **{str(actor_slot): text.strip()})
        phase = "revealed" if len(answers) == 2 else "answering"
        return dict(state, answers=answers, phase=phase)


GAMES = {game.key: game for game in (QuestionsGame(), AnswerRevealGame())}


def get_game(key):
    try:
        return GAMES[key]
    except KeyError:
        raise ActionInvalid("Unknown game.") from None
