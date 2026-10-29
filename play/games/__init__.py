"""Game types: pure functions over a JSON-serialisable state.

A game type never touches the database or the network. The service layer
(play.services) loads the room, checks who is acting, calls the game type,
and stores the result in one transaction.
"""

import random
import re

from chat.reaction_emoji import is_single_emoji
from game.truth_or_dare import DARE, TRUTH, display_text


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
    variants = None  # Every mode.
    shows_names = False

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
    """Questions mode. Each partner may answer the card privately; neither
    answer is sent to the other until both have answered. Answering is
    optional: Next works at any time. Next, Reset and closing the couple
    delete the card's answers, revealed or not, so none are kept."""

    key = "answer_reveal"
    variants = {"questions"}
    shows_names = True  # "<name> has answered".
    MAX_ANSWER = 500

    def start(self, cards, seed):
        return dict(super().start(cards, seed), phase="answering", answers={}, reactions={})

    def apply(self, state, action, actor_slot, cards, payload=None, seed=None):
        if action == "answer":
            return self._answer(state, actor_slot, payload or {})
        if action == "react":
            return self._react(state, actor_slot, payload or {})
        if action == "next":
            return self.forget_answers(super()._next(state, cards))
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
            reactions=self._reactions_view(state, mine, theirs),
        )

    @staticmethod
    def forget_answers(state):
        return dict(state, answers={}, phase="answering", reactions={})

    @staticmethod
    def _reactions_view(state, mine, theirs):
        """{answer: {who: emoji}} from this viewer's side; only revealed
        answers can have reactions."""
        reactions = state.get("reactions", {})
        on_mine, on_theirs = reactions.get(mine, {}), reactions.get(theirs, {})
        return {
            "mine": {"me": on_mine.get(mine), "partner": on_mine.get(theirs)},
            "partner": {"me": on_theirs.get(mine), "partner": on_theirs.get(theirs)},
        }

    def _react(self, state, actor_slot, payload):
        """One emoji per person per revealed answer; null removes it."""
        if state["phase"] != "revealed" or state["current"] is None:
            raise ActionInvalid("You can react once both answers are revealed.")
        if payload.get("card") != state["current"]["key"]:
            raise ActionInvalid("That card has moved on.")
        target = {"mine": actor_slot, "partner": 3 - actor_slot}.get(payload.get("target"))
        emoji = payload.get("emoji")
        if target is None or (emoji is not None and not is_single_emoji(emoji)):
            raise ActionInvalid("Pick a single emoji.")
        reactions = {owner: dict(by) for owner, by in state.get("reactions", {}).items()}
        on_answer = reactions.setdefault(str(target), {})
        if emoji is None:
            on_answer.pop(str(actor_slot), None)
        else:
            on_answer[str(actor_slot)] = emoji
        return dict(state, reactions=reactions)

    def _answer(self, state, actor_slot, payload):
        if state["finished"] or state["current"] is None:
            raise ActionInvalid("There's no card to answer.")
        if payload.get("card") != state["current"]["key"]:
            # Sent for a card that has moved on (the partner pressed Next).
            raise ActionInvalid("That card has moved on.")
        if state["phase"] != "answering":
            raise ActionInvalid("Answers are already revealed.")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > self.MAX_ANSWER:
            raise ActionInvalid(f"Answers need 1 to {self.MAX_ANSWER} characters.")
        answers = dict(state["answers"], **{str(actor_slot): text.strip()})
        phase = "revealed" if len(answers) == 2 else "answering"
        return dict(state, answers=answers, phase=phase)


def split_options(text):
    """The two options of "Would you rather A or B?", or None when that isn't
    certain: then the page offers "Option A" and "Option B" next to the full
    question. ", or" wins (an option may contain "or"); otherwise exactly one
    "or" is needed."""
    match = re.match(r"^\s*would you rather\s+(.+?)\s*\?*\s*$", text or "", re.IGNORECASE)
    if not match:
        return None
    body = match.group(1)
    for separator in (", or ", " or "):
        parts = body.split(separator)
        if len(parts) == 2:
            options = [part.strip(" ,") for part in parts]
            if all(options):
                return [option[0].upper() + option[1:] for option in options]
            return None
        if len(parts) > 2:
            return None
    return None


class PickRevealGame(QuestionsGame):
    """Would You Rather. Each partner privately picks A or B; neither pick is
    sent to the other until both have picked, then both are revealed. A pick
    can change until the reveal. Picking is optional: Next works at any time.
    Next, Reset and closing the couple delete the picks, so none are kept."""

    key = "pick_reveal"
    variants = {"would"}
    shows_names = True  # "<name> has picked".
    CHOICES = ("a", "b")

    def start(self, cards, seed):
        return dict(super().start(cards, seed), phase="picking", picks={})

    def apply(self, state, action, actor_slot, cards, payload=None, seed=None):
        if action == "pick":
            return self._pick(state, actor_slot, payload or {})
        if action == "next":
            return self.forget_answers(super()._next(state, cards))
        return super().apply(state, action, actor_slot, cards, payload, seed)

    def view(self, state, viewer_slot):
        mine, theirs = str(viewer_slot), str(3 - viewer_slot)
        revealed = state["phase"] == "revealed"
        current = state["current"]
        return dict(
            super().view(state, viewer_slot),
            phase=state["phase"],
            options=split_options(current["text"]) if current else None,
            my_pick=state["picks"].get(mine),
            partner_picked=theirs in state["picks"],
            # Only once both have picked; before that it is never sent.
            partner_pick=state["picks"].get(theirs) if revealed else None,
        )

    @staticmethod
    def forget_answers(state):
        """Called on Next and when the couple closes (as for answers)."""
        return dict(state, picks={}, phase="picking")

    def _pick(self, state, actor_slot, payload):
        if state["finished"] or state["current"] is None:
            raise ActionInvalid("There's no card to pick on.")
        if payload.get("card") != state["current"]["key"]:
            raise ActionInvalid("That card has moved on.")
        if state["phase"] != "picking":
            raise ActionInvalid("The picks are already revealed.")
        choice = payload.get("choice")
        if choice not in self.CHOICES:
            raise ActionInvalid("Pick A or B.")
        picks = dict(state["picks"], **{str(actor_slot): choice})
        return dict(state, picks=picks, phase="revealed" if len(picks) == 2 else "picking")


class TruthOrDareGame:
    """Turn-based Truth or Dare. The player whose turn it is picks Truth or
    Dare; the server draws the next card from that pool and the turn passes
    to the partner. The player whose card is up may skip it as often as they
    like: they get the next card of the same kind, the turn stays as it is,
    and the skipped card goes to the bottom of its pool. The first turn is
    random (from the seed). Reset starts again with full pools."""

    key = "truth_or_dare"
    variants = {"truth"}  # The Truth or Dare mode's questions.
    shows_names = True  # The turn banner names the partner.
    POOLS = {TRUTH: "truths", DARE: "dares"}

    def start(self, cards, seed):
        rng = random.Random(seed)
        pools = {kind: [card["key"] for card in as_source(cards).all() if card.get("kind") == kind]
                 for kind in self.POOLS}
        for keys in pools.values():
            rng.shuffle(keys)
        first = rng.choice([1, 2])
        return {
            "truths": pools[TRUTH],
            "dares": pools[DARE],
            "turn": first,
            "first_turn": first,
            "current": None,
            "drawn_by": None,
            "draws": 0,
            "seed": seed,
            "finished": not (pools[TRUTH] or pools[DARE]),
        }

    def apply(self, state, action, actor_slot, cards, payload=None, seed=None):
        if action == "choose":
            return self._choose(state, actor_slot, cards, (payload or {}).get("kind"))
        if action == "skip":
            return self._skip(state, actor_slot, cards)
        if action == "reset":
            return self.start(cards, seed if seed is not None else new_seed())
        raise ActionInvalid("Unknown action.")

    def insert_card(self, state, card, seed):
        """Add a new card to its own pool, at a random place, once."""
        pool = self.POOLS.get(card.get("kind"))
        current = state["current"] or {}
        if pool is None or card["key"] in state[pool] or current.get("key") == card["key"]:
            return state
        keys = list(state[pool])
        keys.insert(random.Random(seed).randint(0, len(keys)), card["key"])
        return dict(state, **{pool: keys}, finished=False)

    def view(self, state, viewer_slot):
        """What a player may see. Pool order stays on the server."""
        current = state["current"]
        if current:
            current = dict(current, text=display_text(current["text"]))
        truths, dares = len(state["truths"]), len(state["dares"])
        return {
            "current": current,
            "your_turn": state["turn"] == viewer_slot,
            "first_turn_yours": state["first_turn"] == viewer_slot,
            "drawn_by_you": state["drawn_by"] == viewer_slot,
            "draws": state["draws"],
            "truths_left": truths,
            "dares_left": dares,
            "remaining": truths + dares,
            "finished": state["finished"],
        }

    def _choose(self, state, actor_slot, cards, kind):
        if kind not in self.POOLS:
            raise ActionInvalid("Choose Truth or Dare.")
        if actor_slot != state["turn"]:
            raise ActionInvalid("It's not your turn.")
        pool = self.POOLS[kind]
        if not state[pool]:
            raise ActionInvalid(f"No {pool} left.")
        keys = list(state[pool])
        drawn = keys.pop(0)
        new = dict(state, **{pool: keys}, current=self._card(cards, drawn, kind), drawn_by=actor_slot,
                   turn=3 - actor_slot, draws=state["draws"] + 1)
        new["finished"] = not (new["truths"] or new["dares"])
        return new

    def _skip(self, state, actor_slot, cards):
        current = state["current"]
        if current is None or state["drawn_by"] != actor_slot:
            raise ActionInvalid("Only the player whose card it is can skip it.")
        kind = current["kind"]
        pool = self.POOLS[kind]
        if not state[pool]:
            raise ActionInvalid(f"That was the last {kind}.")
        keys = list(state[pool]) + [current["key"]]  # Skipped card to the bottom.
        drawn = keys.pop(0)
        return dict(state, **{pool: keys}, current=self._card(cards, drawn, kind))

    @staticmethod
    def _card(cards, key, kind):
        card = as_source(cards).get(key) or {
            "key": key, "text": "(This question was removed.)", "mode": "truth", "custom": False,
        }
        return dict(card, kind=kind)


class ChallengeTurnsGame:
    """Turn-based Challenges (owner, 2026-10-29). The player whose turn it is
    draws the next challenge and the turn passes to the partner. The player
    whose challenge is up may skip it as often as they like: they get the
    next one, the turn stays as it is, and the skipped one goes to the
    bottom of the pile. The first turn is random (from the seed)."""

    key = "challenge_turns"
    variants = {"challenge"}
    shows_names = True  # The turn banner names the partner.

    def start(self, cards, seed):
        rng = random.Random(seed)
        pile = [card["key"] for card in as_source(cards).all()]
        rng.shuffle(pile)
        first = rng.choice([1, 2])
        return {"pile": pile, "turn": first, "first_turn": first, "current": None, "drawn_by": None,
                "draws": 0, "seed": seed, "finished": not pile}

    def apply(self, state, action, actor_slot, cards, payload=None, seed=None):
        if action == "draw":
            return self._draw(state, actor_slot, cards)
        if action == "skip":
            return self._skip(state, actor_slot, cards)
        if action == "reset":
            return self.start(cards, seed if seed is not None else new_seed())
        raise ActionInvalid("Unknown action.")

    def insert_card(self, state, card, seed):
        """Add a new challenge to the pile, at a random place, once."""
        current = state["current"] or {}
        if card["key"] in state["pile"] or current.get("key") == card["key"]:
            return state
        pile = list(state["pile"])
        pile.insert(random.Random(seed).randint(0, len(pile)), card["key"])
        return dict(state, pile=pile, finished=False)

    def view(self, state, viewer_slot):
        """What a player may see. The pile order stays on the server."""
        return {
            "current": state["current"],
            "your_turn": state["turn"] == viewer_slot,
            "first_turn_yours": state["first_turn"] == viewer_slot,
            "drawn_by_you": state["drawn_by"] == viewer_slot,
            "draws": state["draws"],
            "remaining": len(state["pile"]),
            "finished": state["finished"],
        }

    def _draw(self, state, actor_slot, cards):
        if actor_slot != state["turn"]:
            raise ActionInvalid("It's not your turn.")
        if not state["pile"]:
            raise ActionInvalid("No challenges left. Reset to play again.")
        pile = list(state["pile"])
        drawn = pile.pop(0)
        return dict(state, pile=pile, current=self._card(cards, drawn), drawn_by=actor_slot,
                    turn=3 - actor_slot, draws=state["draws"] + 1, finished=not pile)

    def _skip(self, state, actor_slot, cards):
        if state["current"] is None or state["drawn_by"] != actor_slot:
            raise ActionInvalid("Only the player whose challenge it is can skip it.")
        pile = list(state["pile"]) + [state["current"]["key"]]  # Skipped one to the bottom.
        drawn = pile.pop(0)
        return dict(state, pile=pile, current=self._card(cards, drawn), finished=not pile)

    @staticmethod
    def _card(cards, key):
        return as_source(cards).get(key) or {
            "key": key, "text": "(This challenge was removed.)", "mode": "challenge", "custom": False,
        }


GAMES = {game.key: game for game in (QuestionsGame(), AnswerRevealGame(), PickRevealGame(), TruthOrDareGame(),
                                     ChallengeTurnsGame())}


def get_game(key):
    try:
        return GAMES[key]
    except KeyError:
        raise ActionInvalid("Unknown game.") from None
