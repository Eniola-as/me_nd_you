"""The squashed initial migration (0001_squashed_0005) must build exactly
what the original 0001-0005 chain builds, and Django must keep using the
originals for any database that applied only some of them."""

from unittest import skipUnless

from django.apps import apps
from django.db import connection
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ProjectState
from django.test import TestCase, TransactionTestCase

SQUASH = ("game", "0001_squashed_0005_repair_questions")
AFTER_SQUASH = ("game", "0006_custom_question_space")  # First migration after the squash.
ORIGINALS = [
    ("game", "0001_initial"),
    ("game", "0002_load_questions"),
    ("game", "0003_couplesession_last_active_couplesession_session_key_and_more"),
    ("game", "0004_unique_secret_word"),
    ("game", "0005_repair_questions"),
]


def executor(use_squash=True):
    """use_squash=False reproduces a database built from the originals."""
    ex = MigrationExecutor(connection)
    if not use_squash:
        ex.loader = MigrationLoader(connection, replace_migrations=False)
    return ex


def migrate(targets, use_squash=True):
    ex = executor(use_squash)
    ex.migrate(targets)
    return ex


def game_schema():
    """Every game table's columns, keys, constraints and indexes, ignoring
    names and column order (the originals append columns in a different
    order)."""
    intro = connection.introspection
    schema = {}
    with connection.cursor() as cursor:
        tables = sorted(t.name for t in intro.get_table_list(cursor) if t.name.startswith("game_"))
        for table in tables:
            columns = {
                c.name: (intro.get_field_type(c.type_code, c), c.null_ok)
                for c in intro.get_table_description(cursor, table)
            }
            constraints = sorted(
                (
                    tuple(sorted(c["columns"])),
                    bool(c["primary_key"]),
                    bool(c["unique"]),
                    tuple(c["foreign_key"] or ()),
                    bool(c["index"]),
                )
                for c in intro.get_constraints(cursor, table).values()
            )
            schema[table] = (columns, constraints)
    return schema


def question_rows():
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, text, mode FROM game_question ORDER BY id")
        return cursor.fetchall()


class SquashedMigrationTestCase(TransactionTestCase):
    serialized_rollback = True  # Restore the question bank for later tests.

    def tearDown(self):
        # Leave the database fully migrated: the originals (so Django treats
        # the squash as applied), then everything after the squash.
        migrate([ORIGINALS[-1]], use_squash=False)
        ex = executor()
        ex.migrate(ex.loader.graph.leaf_nodes("game"))
        super().tearDown()


class FreshDatabaseTests(TestCase):
    def test_fresh_database_graph_uses_only_the_squash(self):
        graph = MigrationLoader(None, ignore_no_migrations=True).graph
        self.assertIn(SQUASH, graph.nodes)
        for original in ORIGINALS:
            self.assertNotIn(original, graph.nodes)
        # Later migrations build on the squash.
        self.assertIn(SQUASH, {p.key for p in graph.node_map[AFTER_SQUASH].parents})

    def test_models_and_migrations_agree(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        changes = MigrationAutodetector(
            loader.project_state(), ProjectState.from_apps(apps)
        ).changes(graph=loader.graph)
        self.assertNotIn("game", changes)


@skipUnless(connection.vendor == "sqlite", "The original 0003 cannot run on PostgreSQL.")
class SquashMatchesOriginalsTests(SquashedMigrationTestCase):
    def test_squash_builds_the_same_schema_and_data_as_the_originals(self):
        migrate([("game", None)])  # Unapply everything.
        migrate([SQUASH])
        squash_schema, squash_rows = game_schema(), question_rows()
        # Guard against a vacuous comparison.
        self.assertEqual(
            set(squash_schema),
            {"game_couplesession", "game_question", "game_customquestion", "game_playedquestion"},
        )
        couple_constraints = squash_schema["game_couplesession"][1]
        self.assertIn((("secret_word",), False, True, (), False), couple_constraints)
        self.assertGreater(len(squash_rows), 1000)

        migrate([("game", None)])
        migrate([ORIGINALS[-1]], use_squash=False)
        self.assertEqual(game_schema(), squash_schema)
        self.assertEqual(question_rows(), squash_rows)


@skipUnless(connection.vendor == "sqlite", "The original 0003 cannot run on PostgreSQL.")
class ExistingDatabaseTests(SquashedMigrationTestCase):
    def build_squash_reference(self):
        # A fresh database: the squash plus everything after it.
        migrate([("game", None)])
        ex = executor()
        ex.migrate(ex.loader.graph.leaf_nodes("game"))
        return game_schema()

    def test_partially_migrated_database_keeps_using_the_originals(self):
        reference = self.build_squash_reference()
        # Like the local database: 0001-0003 applied, 0004-0005 not.
        migrate([("game", None)])
        migrate([ORIGINALS[2]], use_squash=False)

        graph = MigrationLoader(connection).graph
        self.assertNotIn(SQUASH, graph.nodes)
        self.assertIn(ORIGINALS[3], graph.nodes)

        # 0006 depends on the squash; for this database Django re-points that
        # dependency to the last original, 0005.
        self.assertIn(ORIGINALS[-1], {p.key for p in graph.node_map[AFTER_SQUASH].parents})
        plan = executor().migration_plan(graph.leaf_nodes("game"))
        self.assertEqual(
            [m.name for m, _ in plan],
            ["0004_unique_secret_word", "0005_repair_questions", AFTER_SQUASH[1]],
        )
        executor().migrate(graph.leaf_nodes("game"))
        self.assertEqual(game_schema(), reference)

    def test_fully_migrated_database_counts_the_squash_as_applied(self):
        migrate([("game", None)])
        migrate([ORIGINALS[-1]], use_squash=False)
        loader = MigrationLoader(connection)
        self.assertIn(SQUASH, loader.applied_migrations)
        # Only what comes after the squash remains.
        plan = executor().migration_plan(loader.graph.leaf_nodes("game"))
        self.assertEqual([m.name for m, _ in plan], [AFTER_SQUASH[1]])
