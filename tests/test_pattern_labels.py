"""Tests for structural pattern label extraction and persistence."""

import sqlite3

from mempalace.pattern_labels import (
    PATTERN_DIMENSIONS,
    PATTERN_TAXONOMY,
    PatternExtractor,
    PatternLabelStore,
    backfill_patterns,
    build_extraction_prompt,
    classify_artifact_type,
    extract_and_store_labels,
    load_taxonomy,
    should_skip_pattern_labeling,
)


def test_load_taxonomy_default_dimensions():
    taxonomy = load_taxonomy()
    for dimension in PATTERN_DIMENSIONS:
        assert dimension in taxonomy
        assert taxonomy[dimension]
    assert "workstream" in taxonomy
    assert "decision_driver" in taxonomy
    assert "artifact_type" in taxonomy


def test_build_extraction_prompt_mentions_dimensions():
    prompt = build_extraction_prompt("An intermittent auth bug.", load_taxonomy())
    assert "causal_pattern" in prompt
    assert "workstream" in prompt
    assert "decision_driver" in prompt
    assert "artifact_type" in prompt
    assert "auth bug" in prompt


def test_pattern_extractor_heuristics_detects_auth_pattern(monkeypatch):
    monkeypatch.setenv("MEMPALACE_PATTERN_EXTRACTION_MODE", "heuristic")
    extractor = PatternExtractor()
    result = extractor.extract(
        "Users sometimes get unauthorized errors after token expiry. We reproduced it and fixed the auth middleware.",
        wing="project",
        room="backend",
    )
    labels = result["labels"]
    assert labels["causal_pattern"] == "auth_failure"
    assert labels["temporal_dynamic"] == "intermittent"
    assert labels["confidence"] == "verified"
    assert labels["workstream"] == "debugging"
    assert labels["change_kind"] == "fix"
    assert labels["artifact_type"] == "source_code"


def test_pattern_extractor_heuristics_detects_product_work(monkeypatch):
    monkeypatch.setenv("MEMPALACE_PATTERN_EXTRACTION_MODE", "heuristic")
    extractor = PatternExtractor()
    result = extractor.extract(
        "We ran onboarding interviews, found major signup friction, redesigned the activation flow, and prioritized the experiment from user feedback.",
        wing="product",
        room="research",
    )
    labels = result["labels"]
    assert labels["workstream"] in {"product_discovery", "ux_iteration"}
    assert labels["product_surface"] == "onboarding_activation"
    assert labels["decision_driver"] == "user_feedback"
    assert labels["severity"] == "opportunity"


def test_classify_artifact_type_and_skip_rules():
    assert classify_artifact_type("/tmp/AGENT.md", room="backend") == "agent_guide"
    assert classify_artifact_type("/tmp/foo-plan.md", room="planning") == "plan"
    assert classify_artifact_type("/tmp/package.json", room="backend") == "configuration"
    assert classify_artifact_type("/tmp/.storybook/main.js", room="frontend") == "configuration"
    assert classify_artifact_type("/tmp/example.test.ts", room="testing") == "test_code"
    assert should_skip_pattern_labeling("/tmp/pnpm-lock.yaml", room="testing") is True
    assert should_skip_pattern_labeling("/tmp/image.png", room="documentation") is True
    assert should_skip_pattern_labeling("/tmp/README.md", room="documentation") is False


def test_pattern_label_store_upsert_and_search(tmp_dir):
    store = PatternLabelStore(db_path=f"{tmp_dir}/patterns.sqlite3")
    store.upsert_labels(
        "drawer_1",
        {
            "causal_pattern": "resource_leak",
            "temporal_dynamic": "progressive",
            "topology": "single_component",
            "resolution_strategy": "isolate_reproduce_fix",
            "severity": "degradation",
            "confidence": "verified",
            "workstream": "debugging",
            "change_kind": "fix",
            "product_surface": "backend_system",
            "primary_constraint": "reliability",
            "decision_driver": "incident_signal",
            "artifact_type": "source_code",
        },
        source_wing="project",
        source_room="backend",
    )
    rows = store.search(causal_pattern="resource_leak", workstream="debugging")
    assert len(rows) == 1
    assert rows[0]["episode_id"] == "drawer_1"
    assert rows[0]["source_wing"] == "project"
    assert rows[0]["decision_driver"] == "incident_signal"
    assert rows[0]["artifact_type"] == "source_code"
    store.close()


def test_pattern_label_store_migrates_new_dimensions(tmp_dir):
    db_path = f"{tmp_dir}/patterns.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE pattern_labels (
            episode_id TEXT PRIMARY KEY,
            causal_pattern TEXT,
            temporal_dynamic TEXT,
            topology TEXT,
            resolution_strategy TEXT,
            severity TEXT,
            confidence TEXT,
            extracted_at TEXT NOT NULL,
            source_wing TEXT,
            source_room TEXT
        )
        """
    )
    conn.commit()
    conn.close()

    store = PatternLabelStore(db_path=db_path)
    row = store._conn().execute("PRAGMA table_info(pattern_labels)").fetchall()
    columns = {entry[1] for entry in row}
    assert "workstream" in columns
    assert "decision_driver" in columns
    assert "artifact_type" in columns
    store.close()


def test_extract_and_store_labels(tmp_dir, monkeypatch):
    monkeypatch.setenv("MEMPALACE_PATTERN_EXTRACTION_MODE", "heuristic")
    store = PatternLabelStore(db_path=f"{tmp_dir}/patterns.sqlite3")
    extractor = PatternExtractor()
    result = extract_and_store_labels(
        store,
        extractor,
        "drawer_episode",
        "A dependency upgrade introduced a breaking change. We rolled back the package and added logs before retrying the release.",
        {"wing": "project", "room": "backend", "source_file": "/tmp/service.ts"},
    )
    assert result["labels"]["causal_pattern"] == "dependency_break"
    assert result["labels"]["resolution_strategy"] == "rollback"
    assert result["labels"]["workstream"] in {"migration", "debugging"}
    assert result["labels"]["artifact_type"] == "source_code"
    stored = store.get_labels("drawer_episode")
    assert stored is not None
    assert stored["source_room"] == "backend"
    store.close()


def test_extract_and_store_labels_skips_low_signal_files(tmp_dir, monkeypatch):
    monkeypatch.setenv("MEMPALACE_PATTERN_EXTRACTION_MODE", "heuristic")
    store = PatternLabelStore(db_path=f"{tmp_dir}/patterns.sqlite3")
    extractor = PatternExtractor()
    result = extract_and_store_labels(
        store,
        extractor,
        "drawer_lockfile",
        "storybook onboarding dependency lock data",
        {"wing": "project", "room": "testing", "source_file": "/tmp/pnpm-lock.yaml"},
    )
    assert result["skipped"] is True
    assert store.get_labels("drawer_lockfile") is None
    store.close()


def test_storybook_is_classified_as_developer_experience(monkeypatch):
    monkeypatch.setenv("MEMPALACE_PATTERN_EXTRACTION_MODE", "heuristic")
    extractor = PatternExtractor()
    result = extractor.extract(
        "Storybook onboarding addon and React Vite workspace setup.",
        wing="project",
        room="frontend",
        source_file="/tmp/.storybook/main.js",
    )
    labels = result["labels"]
    assert labels["artifact_type"] == "configuration"
    assert labels["workstream"] == "developer_experience"
    assert labels["product_surface"] == "developer_workflow"


def test_backfill_patterns_uses_existing_drawers(palace_path, seeded_collection, monkeypatch):
    monkeypatch.setenv("MEMPALACE_PATTERN_EXTRACTION_MODE", "heuristic")
    result = backfill_patterns(palace_path)
    assert result["processed"] == seeded_collection.count()
    assert result["labeled"] == seeded_collection.count()

    store = PatternLabelStore.for_palace(palace_path)
    stats = store.list_patterns()
    assert stats["episodes_labeled"] == seeded_collection.count()
    assert set(PATTERN_TAXONOMY).issuperset(stats["dimensions"].keys())
    store.close()
