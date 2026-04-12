#!/usr/bin/env python3
"""
pattern_labels.py — Structural pattern taxonomy, extraction, and SQLite storage.

This layer is intentionally additive:
  - drawers stay in ChromaDB
  - AAAK stays unchanged
  - structural labels live in a small local SQLite store
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Optional

import chromadb
import yaml


DEFAULT_TAXONOMY = {
    "causal_pattern": [
        "resource_leak",
        "missing_validation",
        "race_condition",
        "config_conflict",
        "state_desync",
        "dependency_break",
        "auth_failure",
        "silent_error",
        "interface_mismatch",
        "hidden_coupling",
        "incorrect_assumption",
        "observability_gap",
        "capacity_limit",
        "data_quality_issue",
        "workflow_gap",
        "user_friction",
        "unclear_requirements",
        "prioritization_gap",
        "coordination_gap",
        "opportunity_gap",
    ],
    "temporal_dynamic": [
        "immediate",
        "progressive",
        "intermittent",
        "event_triggered",
        "delayed",
        "recurring",
        "cascading",
        "long_running",
        "deadline_driven",
        "release_bound",
    ],
    "topology": [
        "single_component",
        "linear_chain",
        "circular",
        "fan_out",
        "cross_service",
        "cross_repo",
        "multi_layer",
        "data_pipeline",
        "control_plane",
        "user_journey",
        "multi_actor",
        "platform_surface",
    ],
    "resolution_strategy": [
        "isolate_reproduce_fix",
        "workaround_then_fix",
        "rollback",
        "refactor",
        "config_change",
        "upstream_fix",
        "instrument_then_iterate",
        "prototype_and_validate",
        "simplify_scope",
        "redesign_flow",
        "align_stakeholders",
        "document_and_enable",
        "automate_and_guardrail",
    ],
    "severity": [
        "blocker",
        "critical",
        "major",
        "degradation",
        "minor",
        "cosmetic",
        "strategic",
        "security",
        "compliance",
        "opportunity",
    ],
    "confidence": ["verified", "probable", "mixed_signal", "hypothesis", "exploratory"],
    "workstream": [
        "debugging",
        "feature_delivery",
        "refactor",
        "architecture",
        "migration",
        "performance",
        "developer_experience",
        "research",
        "product_discovery",
        "product_strategy",
        "ux_iteration",
        "release_operations",
    ],
    "change_kind": [
        "fix",
        "add",
        "improve",
        "redesign",
        "simplify",
        "migrate",
        "validate",
        "automate",
        "document",
        "decide",
    ],
    "product_surface": [
        "backend_system",
        "frontend_ui",
        "api_contract",
        "data_model",
        "infra_platform",
        "developer_workflow",
        "onboarding_activation",
        "core_user_flow",
        "admin_operations",
        "analytics_instrumentation",
        "monetization_pricing",
        "retention_engagement",
        "collaboration_workflow",
    ],
    "primary_constraint": [
        "correctness",
        "reliability",
        "performance",
        "security",
        "usability",
        "maintainability",
        "scalability",
        "cost",
        "delivery_speed",
        "compliance",
        "adoption",
    ],
    "decision_driver": [
        "incident_signal",
        "user_feedback",
        "metric_signal",
        "stakeholder_request",
        "strategic_bet",
        "technical_constraint",
        "market_signal",
        "team_capacity",
        "regulatory_need",
        "competitive_pressure",
    ],
    "artifact_type": [
        "source_code",
        "test_code",
        "configuration",
        "documentation",
        "specification",
        "plan",
        "agent_guide",
        "schema",
        "script",
        "template",
        "generated_asset",
        "dataset",
    ],
}

TAXONOMY_FILENAME = "taxonomy.yaml"

_REPO_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / TAXONOMY_FILENAME
_PACKAGE_TAXONOMY_PATH = Path(__file__).with_name(TAXONOMY_FILENAME)

_DIMENSION_DEFAULTS = {
    "temporal_dynamic": "immediate",
    "topology": "single_component",
    "confidence": "probable",
}

_SKIP_FILE_BASENAMES = {
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "cargo.lock",
    "poetry.lock",
    "composer.lock",
}

_SKIP_FILE_SUFFIXES = {
    ".lock",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".wav",
    ".mp4",
    ".mov",
    ".zip",
    ".gz",
}

_AGENT_GUIDE_FILENAMES = {"agent.md", "agents.md", "skill.md"}

_HEURISTIC_RULES = {
    "causal_pattern": {
        "resource_leak": [
            r"\bmemory leak\b",
            r"\bresource leak\b",
            r"\bleak(?:ed|ing)?\b",
            r"\bout of memory\b",
            r"\boom\b",
            r"\bunclosed\b",
            r"\bfile handle\b",
            r"\bconnection leak\b",
        ],
        "missing_validation": [
            r"\bmissing validation\b",
            r"\bvalidate\b",
            r"\bvalidation\b",
            r"\binvalid input\b",
            r"\bunchecked\b",
            r"\bsanitiz(?:e|ed|ing)\b",
        ],
        "race_condition": [
            r"\brace condition\b",
            r"\bdata race\b",
            r"\bthread safety\b",
            r"\bconcurrent\b",
            r"\bdeadlock\b",
            r"\btiming issue\b",
        ],
        "config_conflict": [
            r"\bconfig(?:uration)?\b",
            r"\bmisconfig(?:ured|uration)?\b",
            r"\benv(?:ironment)? variable\b",
            r"\bfeature flag\b",
            r"\bsettings?\b",
            r"\bconflict\b",
            r"\bmismatch\b",
            r"\btoggle\b",
        ],
        "state_desync": [
            r"\bout of sync\b",
            r"\bdesync\b",
            r"\bstale state\b",
            r"\bstale cache\b",
            r"\bcache invalidation\b",
            r"\binconsistent state\b",
            r"\bdrift\b",
        ],
        "dependency_break": [
            r"\bdependency\b",
            r"\bpackage\b",
            r"\blibrary\b",
            r"\bupgrade\b",
            r"\bversion mismatch\b",
            r"\bbreaking change\b",
            r"\bmodule not found\b",
        ],
        "auth_failure": [
            r"\bauth\b",
            r"\bauthentication\b",
            r"\bauthori[sz]ation\b",
            r"\bpermission denied\b",
            r"\bunauthori[sz]ed\b",
            r"\bforbidden\b",
            r"\btoken expired\b",
            r"\blogin failed\b",
        ],
        "silent_error": [
            r"\bsilent(?:ly)?\b",
            r"\bno error\b",
            r"\bswallow(?:ed)? exception\b",
            r"\bhidden failure\b",
            r"\bwithout error\b",
            r"\bno stack trace\b",
        ],
        "interface_mismatch": [
            r"\binterface mismatch\b",
            r"\bcontract mismatch\b",
            r"\bwrong payload\b",
            r"\bwrong schema\b",
            r"\bshape mismatch\b",
            r"\bapi contract\b",
        ],
        "hidden_coupling": [
            r"\bcoupl(?:ed|ing)\b",
            r"\bhidden dependency\b",
            r"\bside effect\b",
            r"\btightly coupled\b",
            r"\bshared mutable state\b",
        ],
        "incorrect_assumption": [
            r"\bassum(?:e|ed|ption)\b",
            r"\bturns out\b",
            r"\bwe thought\b",
            r"\bwrong mental model\b",
            r"\bexpected .* but\b",
        ],
        "observability_gap": [
            r"\bmissing logs?\b",
            r"\bno logs?\b",
            r"\bno metrics?\b",
            r"\bno tracing\b",
            r"\bobservability\b",
            r"\bdebug blind\b",
        ],
        "capacity_limit": [
            r"\bcapacity\b",
            r"\brate limit\b",
            r"\bthrottl(?:e|ing)\b",
            r"\bsaturated\b",
            r"\bqueue backlog\b",
            r"\bload spike\b",
        ],
        "data_quality_issue": [
            r"\bbad data\b",
            r"\bdirty data\b",
            r"\bnull values\b",
            r"\bduplicate rows\b",
            r"\binvalid records\b",
            r"\bdata quality\b",
        ],
        "workflow_gap": [
            r"\bmanual step\b",
            r"\bworkflow gap\b",
            r"\bmissing process\b",
            r"\bhand[- ]off\b",
            r"\boperational gap\b",
            r"\brunbook\b",
        ],
        "user_friction": [
            r"\bfriction\b",
            r"\bconfusing\b",
            r"\bdrop[- ]?off\b",
            r"\btoo many steps\b",
            r"\bunusable\b",
            r"\bpain point\b",
        ],
        "unclear_requirements": [
            r"\bunclear requirement\b",
            r"\bambiguous\b",
            r"\bspec(?:ification)? gap\b",
            r"\bnot defined\b",
            r"\bundefined behavior\b",
        ],
        "prioritization_gap": [
            r"\bpriorit(?:y|ization)\b",
            r"\broadmap\b",
            r"\bnot now\b",
            r"\btrade[- ]?off\b",
            r"\bscope pressure\b",
        ],
        "coordination_gap": [
            r"\bcoordination\b",
            r"\bmisaligned\b",
            r"\bwaiting on\b",
            r"\bblocked by another team\b",
            r"\bowner unclear\b",
        ],
        "opportunity_gap": [
            r"\bopportunity\b",
            r"\buntapped\b",
            r"\bgrowth gap\b",
            r"\bactivation gap\b",
            r"\bretention gap\b",
            r"\bconversion gap\b",
        ],
    },
    "temporal_dynamic": {
        "immediate": [
            r"\bimmediate(?:ly)?\b",
            r"\binstantly\b",
            r"\bon startup\b",
            r"\bat startup\b",
            r"\bright away\b",
        ],
        "progressive": [
            r"\bprogressive\b",
            r"\bgradual\b",
            r"\bover time\b",
            r"\bafter a while\b",
            r"\bbuilds up\b",
        ],
        "intermittent": [
            r"\bintermittent\b",
            r"\bflaky\b",
            r"\bsporadic\b",
            r"\brandom(?:ly)?\b",
            r"\bsometimes\b",
            r"\boccasionally\b",
        ],
        "event_triggered": [
            r"\btriggered by\b",
            r"\bwhen clicking\b",
            r"\bon save\b",
            r"\bupon\b",
            r"\bduring upload\b",
        ],
        "delayed": [
            r"\bdelayed\b",
            r"\blater\b",
            r"\bafter restart\b",
            r"\blag(?:ging)?\b",
            r"\bafter \d+ (?:seconds?|minutes?|hours?|days?)\b",
        ],
        "recurring": [r"\bevery sprint\b", r"\brecurring\b", r"\bkeeps happening\b"],
        "cascading": [
            r"\bcascade\b",
            r"\bknock-on\b",
            r"\bdomino effect\b",
            r"\bdownstream failures?\b",
        ],
        "long_running": [r"\blong[- ]?running\b", r"\bongoing\b", r"\bchronic\b"],
        "deadline_driven": [
            r"\bdeadline\b",
            r"\btime pressure\b",
            r"\bship date\b",
            r"\bby friday\b",
        ],
        "release_bound": [r"\brelease\b", r"\blaunch\b", r"\bcutoff\b", r"\bfreeze\b"],
    },
    "topology": {
        "linear_chain": [r"\bchain\b", r"\bpipeline\b", r"\brequest flow\b", r"\bproxy\b"],
        "circular": [r"\bcircular\b", r"\bfeedback loop\b", r"\bcycle\b", r"\brecursion\b"],
        "fan_out": [
            r"\bfan[- ]?out\b",
            r"\bbroadcast\b",
            r"\bscatter\b",
            r"\bmultiple consumers\b",
        ],
        "cross_service": [
            r"\bcross[- ]?service\b",
            r"\bservice to service\b",
            r"\bmicroservice\b",
            r"\bupstream service\b",
            r"\bdownstream service\b",
            r"\brpc\b",
        ],
        "cross_repo": [
            r"\bcross[- ]?repo\b",
            r"\bmultiple repos\b",
            r"\bmonorepo\b",
            r"\bshared library repo\b",
        ],
        "multi_layer": [r"\blayer\b", r"\bstack\b", r"\bfrontend and backend\b"],
        "data_pipeline": [r"\betl\b", r"\bdata pipeline\b", r"\bingestion\b", r"\bwarehouse\b"],
        "control_plane": [r"\bcontrol plane\b", r"\boperator\b", r"\borchestr(?:ation|ator)\b"],
        "user_journey": [
            r"\bjourney\b",
            r"\bfunnel\b",
            r"\bonboarding\b",
            r"\bsignup flow\b",
            r"\bcheckout\b",
        ],
        "multi_actor": [r"\bstakeholder\b", r"\bteam\b", r"\buser and admin\b", r"\bapproval\b"],
        "platform_surface": [r"\bplatform\b", r"\bshared surface\b", r"\bextensibility\b"],
    },
    "resolution_strategy": {
        "isolate_reproduce_fix": [
            r"\bisolat(?:e|ed|ing)\b",
            r"\breproduc(?:e|ed|ible)\b",
            r"\bminimal repro\b",
            r"\broot cause\b",
            r"\bfix(?:ed)? by\b",
        ],
        "workaround_then_fix": [
            r"\bworkaround\b",
            r"\btemporary fix\b",
            r"\bhotfix\b",
            r"\bmitigation\b",
        ],
        "rollback": [
            r"\brollback\b",
            r"\broll back\b",
            r"\brolled back\b",
            r"\brevert(?:ed)?\b",
            r"\bbacked out\b",
        ],
        "refactor": [
            r"\brefactor(?:ed|ing)?\b",
            r"\brewrite\b",
            r"\bre-architect\b",
            r"\brestructured\b",
        ],
        "config_change": [
            r"\bconfig change\b",
            r"\bchanged config\b",
            r"\breconfigured\b",
            r"\bupdated env\b",
            r"\bflag flip\b",
        ],
        "upstream_fix": [
            r"\bupstream\b",
            r"\bvendor\b",
            r"\bopened a pr\b",
            r"\bwaited for release\b",
        ],
        "instrument_then_iterate": [
            r"\binstrument\b",
            r"\badd(?:ed)? logging\b",
            r"\bmeasure first\b",
            r"\btrace\b",
        ],
        "prototype_and_validate": [
            r"\bprototype\b",
            r"\bspike\b",
            r"\bexperiment\b",
            r"\bvalidate\b",
        ],
        "simplify_scope": [
            r"\bsimplif(?:y|ied)\b",
            r"\bcut scope\b",
            r"\bde-scoped\b",
            r"\breduce scope\b",
        ],
        "redesign_flow": [
            r"\bredesign\b",
            r"\breworked flow\b",
            r"\bchanged journey\b",
            r"\bnew flow\b",
        ],
        "align_stakeholders": [
            r"\balign(?:ed|ment)?\b",
            r"\bconsensus\b",
            r"\bdecision meeting\b",
            r"\bstakeholder sign-off\b",
        ],
        "document_and_enable": [
            r"\bdocument(?:ed)?\b",
            r"\brunbook\b",
            r"\bplaybook\b",
            r"\bguide\b",
        ],
        "automate_and_guardrail": [
            r"\bautomate\b",
            r"\bguardrail\b",
            r"\bci check\b",
            r"\blint rule\b",
            r"\balerting\b",
        ],
    },
    "severity": {
        "blocker": [r"\bblocker\b", r"\bproduction down\b", r"\bcannot\b", r"\bcan'?t\b"],
        "critical": [r"\bcritical\b", r"\bsev1\b", r"\bhigh risk\b", r"\boutage\b"],
        "major": [r"\bmajor\b", r"\bhigh impact\b", r"\bserious\b"],
        "degradation": [
            r"\bslow\b",
            r"\bdegrad(?:ation|ed)?\b",
            r"\bpartial failure\b",
            r"\blatency\b",
        ],
        "minor": [r"\bminor\b", r"\blow impact\b", r"\bedge case\b"],
        "cosmetic": [r"\bcosmetic\b", r"\bui glitch\b", r"\btypo\b", r"\bspacing\b"],
        "strategic": [r"\bstrategic\b", r"\broadmap\b", r"\bplatform bet\b", r"\blong-term\b"],
        "security": [
            r"\bsecurity\b",
            r"\bvulnerability\b",
            r"\bcredential\b",
            r"\bxss\b",
            r"\bcve\b",
        ],
        "compliance": [
            r"\bcompliance\b",
            r"\bprivacy\b",
            r"\bgdpr\b",
            r"\bsox\b",
            r"\bregulatory\b",
        ],
        "opportunity": [r"\bopportunity\b", r"\bgrowth\b", r"\bconversion\b", r"\bretention\b"],
    },
    "confidence": {
        "verified": [
            r"\bverified\b",
            r"\bconfirmed\b",
            r"\breproduced\b",
            r"\btested\b",
            r"\bresolved\b",
        ],
        "probable": [r"\bprobable\b", r"\blikely\b", r"\bseems\b", r"\bappears\b", r"\bsuspect\b"],
        "mixed_signal": [r"\bmixed signals?\b", r"\binconclusive\b", r"\bconflicting data\b"],
        "hypothesis": [
            r"\bhypothesis\b",
            r"\bmaybe\b",
            r"\bmight\b",
            r"\bcould be\b",
            r"\bnot sure\b",
        ],
        "exploratory": [r"\bexplor(?:e|atory)\b", r"\bspike\b", r"\blearning\b", r"\bdiscovery\b"],
    },
    "workstream": {
        "debugging": [r"\bbug\b", r"\bdebug\b", r"\bincident\b", r"\bfix\b", r"\berror\b"],
        "feature_delivery": [
            r"\bfeature\b",
            r"\bimplement\b",
            r"\bbuild\b",
            r"\bship\b",
            r"\badd\b",
        ],
        "refactor": [r"\brefactor\b", r"\bcleanup\b", r"\bsimplify code\b", r"\btech debt\b"],
        "architecture": [
            r"\barchitecture\b",
            r"\bdesign\b",
            r"\bmodule boundary\b",
            r"\bsystem design\b",
        ],
        "migration": [r"\bmigrate\b", r"\bupgrade\b", r"\bport\b", r"\btransition\b"],
        "performance": [r"\bperformance\b", r"\boptimi[sz]e\b", r"\blatency\b", r"\bthroughput\b"],
        "developer_experience": [
            r"\bdx\b",
            r"\bdeveloper experience\b",
            r"\btooling\b",
            r"\bci\b",
            r"\blocal setup\b",
        ],
        "research": [
            r"\bresearch\b",
            r"\bevaluate\b",
            r"\bcompare\b",
            r"\bbenchmark\b",
            r"\bspike\b",
        ],
        "product_discovery": [
            r"\binterview\b",
            r"\bdiscovery\b",
            r"\bproblem space\b",
            r"\buser research\b",
        ],
        "product_strategy": [
            r"\broadmap\b",
            r"\bpricing\b",
            r"\bpositioning\b",
            r"\bpriorit(?:y|ization)\b",
        ],
        "ux_iteration": [
            r"\bonboarding\b",
            r"\busability\b",
            r"\bflow\b",
            r"\bcopy\b",
            r"\bwireframe\b",
        ],
        "release_operations": [
            r"\brelease\b",
            r"\blaunch\b",
            r"\brollout\b",
            r"\bfreeze\b",
            r"\bdeploy plan\b",
        ],
    },
    "change_kind": {
        "fix": [r"\bfix(?:ed)?\b", r"\bresolved\b", r"\bpatched\b"],
        "add": [r"\badd(?:ed)?\b", r"\bnew\b", r"\bimplemented\b", r"\bbuilt\b"],
        "improve": [r"\bimprov(?:e|ed|ement)\b", r"\boptimi[sz]e\b", r"\benhance\b"],
        "redesign": [r"\bredesign\b", r"\breworked\b", r"\brethought\b"],
        "simplify": [r"\bsimplif(?:y|ied)\b", r"\breduce complexity\b", r"\bremove step\b"],
        "migrate": [r"\bmigrate\b", r"\bupgrade\b", r"\bport\b", r"\bmove to\b"],
        "validate": [r"\bvalidate\b", r"\btest(?:ed)?\b", r"\bexperiment\b", r"\binterview\b"],
        "automate": [r"\bautomate\b", r"\bscript\b", r"\bgenerated?\b", r"\bworkflow automation\b"],
        "document": [r"\bdocument(?:ed)?\b", r"\bdocs?\b", r"\bguide\b", r"\brunbook\b"],
        "decide": [r"\bdecid(?:e|ed)\b", r"\bchose\b", r"\bprioriti[sz]e\b", r"\baligned on\b"],
    },
    "product_surface": {
        "backend_system": [r"\bbackend\b", r"\bworker\b", r"\bservice\b", r"\bqueue\b"],
        "frontend_ui": [r"\bfrontend\b", r"\bui\b", r"\bcomponent\b", r"\bpage\b", r"\bscreen\b"],
        "api_contract": [
            r"\bapi\b",
            r"\bendpoint\b",
            r"\bcontract\b",
            r"\bschema\b",
            r"\bgraphql\b",
        ],
        "data_model": [r"\bdatabase\b", r"\bsql\b", r"\btable\b", r"\bmodel\b", r"\bmigration\b"],
        "infra_platform": [
            r"\binfra\b",
            r"\bdeployment\b",
            r"\bkubernetes\b",
            r"\bterraform\b",
            r"\bcloud\b",
        ],
        "developer_workflow": [
            r"\bci\b",
            r"\btest suite\b",
            r"\blint\b",
            r"\bbuild pipeline\b",
            r"\bdev environment\b",
        ],
        "onboarding_activation": [
            r"\bonboarding\b",
            r"\bactivation\b",
            r"\bsignup\b",
            r"\bfirst-run\b",
        ],
        "core_user_flow": [
            r"\bcheckout\b",
            r"\bsearch flow\b",
            r"\bmain flow\b",
            r"\bprimary action\b",
        ],
        "admin_operations": [r"\badmin\b", r"\bops\b", r"\bbackoffice\b", r"\bmoderation\b"],
        "analytics_instrumentation": [
            r"\banalytics\b",
            r"\btracking\b",
            r"\bmetric\b",
            r"\binstrumentation\b",
        ],
        "monetization_pricing": [
            r"\bpricing\b",
            r"\bbilling\b",
            r"\bsubscription\b",
            r"\bpaywall\b",
        ],
        "retention_engagement": [
            r"\bretention\b",
            r"\bengagement\b",
            r"\bchurn\b",
            r"\bre-engagement\b",
        ],
        "collaboration_workflow": [
            r"\bcollaboration\b",
            r"\bsharing\b",
            r"\bcommenting\b",
            r"\bapproval flow\b",
        ],
    },
    "primary_constraint": {
        "correctness": [r"\bcorrect(?:ness)?\b", r"\bwrong result\b", r"\baccuracy\b"],
        "reliability": [r"\breliability\b", r"\bstability\b", r"\bavailability\b", r"\bincident\b"],
        "performance": [r"\bperformance\b", r"\blatency\b", r"\bthroughput\b", r"\bfast\b"],
        "security": [
            r"\bsecurity\b",
            r"\bcredential\b",
            r"\bvulnerability\b",
            r"\baccess control\b",
        ],
        "usability": [r"\busability\b", r"\bconfusing\b", r"\blearnability\b", r"\bux\b"],
        "maintainability": [
            r"\bmaintainability\b",
            r"\btech debt\b",
            r"\breadability\b",
            r"\bcleaner\b",
        ],
        "scalability": [r"\bscale\b", r"\bscalability\b", r"\btraffic\b", r"\bload\b"],
        "cost": [r"\bcost\b", r"\bexpensive\b", r"\bcloud spend\b", r"\btoken cost\b"],
        "delivery_speed": [
            r"\bspeed\b",
            r"\bquickly\b",
            r"\bfast iteration\b",
            r"\bdeveloper velocity\b",
        ],
        "compliance": [r"\bcompliance\b", r"\bprivacy\b", r"\bregulatory\b", r"\baudit\b"],
        "adoption": [r"\badoption\b", r"\bactivation\b", r"\bconversion\b", r"\bretention\b"],
    },
    "decision_driver": {
        "incident_signal": [r"\bincident\b", r"\boutage\b", r"\bpostmortem\b", r"\bpage\b"],
        "user_feedback": [
            r"\buser feedback\b",
            r"\binterview\b",
            r"\bcustomer\b",
            r"\bsupport ticket\b",
        ],
        "metric_signal": [r"\bmetric\b", r"\bdata showed\b", r"\bdrop-off\b", r"\bbenchmark\b"],
        "stakeholder_request": [
            r"\bstakeholder\b",
            r"\bleadership request\b",
            r"\basked by\b",
            r"\bpartner request\b",
        ],
        "strategic_bet": [
            r"\bstrategic bet\b",
            r"\blong-term\b",
            r"\bpositioning\b",
            r"\broadmap bet\b",
        ],
        "technical_constraint": [
            r"\bconstraint\b",
            r"\blimitation\b",
            r"\bcompatibility\b",
            r"\blegacy\b",
        ],
        "market_signal": [
            r"\bmarket\b",
            r"\bcompetitor\b",
            r"\bsegment\b",
            r"\bpricing pressure\b",
        ],
        "team_capacity": [r"\bcapacity\b", r"\bsmall team\b", r"\bbandwidth\b", r"\bheadcount\b"],
        "regulatory_need": [r"\bregulatory\b", r"\bcompliance\b", r"\bprivacy\b", r"\bpolicy\b"],
        "competitive_pressure": [
            r"\bcompetitive\b",
            r"\bcompetitor\b",
            r"\bparity\b",
            r"\bdifferentiation\b",
        ],
    },
}


def _taxonomy_copy() -> dict:
    return deepcopy(DEFAULT_TAXONOMY)


def _normalize_label(value: str) -> Optional[str]:
    if value is None:
        return None
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return normalized or None


def _normalize_dimension_name(value: str) -> Optional[str]:
    return _normalize_label(value)


def _normalize_taxonomy(raw: dict) -> dict:
    normalized = {}
    if not isinstance(raw, dict):
        return normalized

    for raw_dimension, raw_values in raw.items():
        dimension = _normalize_dimension_name(raw_dimension)
        if not dimension or not isinstance(raw_values, list):
            continue
        values = []
        for raw_value in raw_values:
            value = _normalize_label(raw_value)
            if value and value not in values:
                values.append(value)
        if values:
            normalized[dimension] = values
    return normalized


def _validate_taxonomy(raw: dict) -> dict:
    normalized = _normalize_taxonomy(raw)
    taxonomy = {}

    for dimension, values in DEFAULT_TAXONOMY.items():
        taxonomy[dimension] = normalized.pop(dimension, list(values))

    for dimension, values in normalized.items():
        taxonomy[dimension] = values

    return taxonomy


def load_taxonomy(taxonomy_path: str = None) -> dict:
    """Load taxonomy from YAML, falling back to the baked-in defaults."""
    candidates = []
    if taxonomy_path:
        candidates.append(Path(taxonomy_path).expanduser())
    candidates.extend([_REPO_TAXONOMY_PATH, _PACKAGE_TAXONOMY_PATH])

    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            with open(candidate, encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle) or {}
            return _validate_taxonomy(loaded)
        except (OSError, yaml.YAMLError, ValueError):
            continue

    return _taxonomy_copy()


PATTERN_TAXONOMY = load_taxonomy()
PATTERN_DIMENSIONS = tuple(PATTERN_TAXONOMY.keys())


def build_extraction_prompt(content: str, taxonomy: dict) -> str:
    excerpt = content.strip()[:6000]
    compact_taxonomy = "; ".join(
        f"{dimension}=[{', '.join(values)}]" for dimension, values in taxonomy.items()
    )
    keys = ", ".join(taxonomy.keys())
    return (
        "Classify this engineering, delivery, or product episode using the fixed taxonomy below. "
        "Return JSON only, with one key per dimension. "
        f"Taxonomy: {compact_taxonomy}. "
        f"Required keys: {keys}. "
        f"Episode:\n{excerpt}"
    )


def _extract_json_object(text: str) -> Optional[dict]:
    if not text:
        return None

    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _score_dimension(text: str, rules: dict, default: str = None) -> Optional[str]:
    if not rules:
        return default

    scores = {value: 0 for value in rules}
    for value, patterns in rules.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                scores[value] += 1

    best_value = max(scores, key=scores.get)
    if scores[best_value] > 0:
        return best_value
    return default


def classify_artifact_type(source_file: str = None, room: str = None) -> str:
    path = Path(source_file or "")
    filename = path.name.lower()
    suffix = path.suffix.lower()
    room_name = (room or "").lower()
    parts = {part.lower() for part in path.parts}

    if ".storybook" in parts:
        return "configuration"
    if filename in _AGENT_GUIDE_FILENAMES:
        return "agent_guide"
    if filename.endswith("-plan.md") or "planning" in parts or room_name == "planning":
        return "plan"
    if "spec" in filename or "specification" in filename or filename.endswith("-spec.md"):
        return "specification"
    if suffix in {
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".env",
        ".conf",
        ".config",
        ".config.js",
        ".config.ts",
    }:
        if "schema" in filename:
            return "schema"
        return "configuration"
    if suffix in {".sql"} or "schema" in filename:
        return "schema"
    if suffix in {".sh", ".ps1", ".bat"} or room_name in {"script", "scripts"}:
        return "script"
    if filename.endswith(".template.md") or "template" in filename:
        return "template"
    if suffix in {".md", ".mdx", ".txt"}:
        return "documentation"
    if "test" in filename or room_name == "testing":
        return "test_code"
    if suffix in {
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".py",
        ".go",
        ".rb",
        ".java",
        ".kt",
        ".rs",
        ".php",
        ".cs",
    }:
        return "source_code"
    if suffix in {".csv", ".jsonl"}:
        return "dataset"
    if not filename:
        return "source_code"
    return "generated_asset"


def should_skip_pattern_labeling(source_file: str = None, room: str = None) -> bool:
    path = Path(source_file or "")
    filename = path.name.lower()
    suffix = path.suffix.lower()
    parts = {part.lower() for part in path.parts}
    artifact_type = classify_artifact_type(source_file=source_file, room=room)

    if not filename:
        return False

    if filename in _SKIP_FILE_BASENAMES:
        return True
    if suffix in _SKIP_FILE_SUFFIXES:
        return True
    if artifact_type == "generated_asset":
        return True
    if "node_modules" in parts or "dist" in parts or "build" in parts or ".next" in parts:
        return True
    return False


class PatternExtractor:
    """Extract structural labels from a drawer or episode."""

    def __init__(self, taxonomy_path: str = None, taxonomy: dict = None):
        if taxonomy is not None:
            self.taxonomy = deepcopy(taxonomy)
        elif taxonomy_path:
            self.taxonomy = load_taxonomy(taxonomy_path)
        else:
            self.taxonomy = deepcopy(PATTERN_TAXONOMY)
        self.dimensions = tuple(self.taxonomy.keys())

    def extract(
        self,
        content: str,
        wing: str = None,
        room: str = None,
        source_file: str = None,
    ) -> dict:
        heuristics = self._extract_heuristic(content, wing=wing, room=room, source_file=source_file)
        llm_labels = self._extract_via_llm(content)

        labels = dict(heuristics)
        source = "heuristic"
        if llm_labels:
            labels.update({key: value for key, value in llm_labels.items() if value is not None})
            source = "llm"

        return {"labels": self._coerce_labels(labels), "source": source}

    def _coerce_labels(self, labels: dict) -> dict:
        coerced = {}
        for dimension, allowed_values in self.taxonomy.items():
            value = _normalize_label(labels.get(dimension))
            coerced[dimension] = value if value in set(allowed_values) else None
        return coerced

    def _extract_heuristic(
        self,
        content: str,
        wing: str = None,
        room: str = None,
        source_file: str = None,
    ) -> dict:
        combined = " ".join(
            part for part in [wing or "", room or "", content.strip().lower()] if part
        )

        labels = {}
        for dimension in self.dimensions:
            labels[dimension] = _score_dimension(
                combined,
                _HEURISTIC_RULES.get(dimension, {}),
                default=_DIMENSION_DEFAULTS.get(dimension),
            )

        labels["artifact_type"] = labels.get("artifact_type") or classify_artifact_type(
            source_file=source_file,
            room=room,
        )

        if labels.get("temporal_dynamic") == "immediate" and re.search(
            r"\bwhen\b|\bon click\b|\bon submit\b|\bon deploy\b", combined, re.IGNORECASE
        ):
            labels["temporal_dynamic"] = "event_triggered"

        if labels.get("severity") in {None, "minor", "degradation"} and re.search(
            r"\bblocker\b|\bproduction down\b|\bcannot\b|\bcan't\b", combined, re.IGNORECASE
        ):
            labels["severity"] = "blocker"

        if labels.get("severity") != "security" and re.search(
            r"\bsecurity\b|\bsecret\b|\bcredential\b|\btoken leak\b|\bxss\b",
            combined,
            re.IGNORECASE,
        ):
            labels["severity"] = "security"
            labels["primary_constraint"] = "security"

        if labels.get("severity") != "compliance" and re.search(
            r"\bcompliance\b|\bprivacy\b|\bgdpr\b|\bpolicy\b",
            combined,
            re.IGNORECASE,
        ):
            labels["severity"] = "compliance"
            labels["primary_constraint"] = "compliance"
            labels["decision_driver"] = "regulatory_need"

        if labels.get("confidence") == "probable" and re.search(
            r"\bverified\b|\bconfirmed\b|\btested\b|\bresolved\b|\breproduced\b",
            combined,
            re.IGNORECASE,
        ):
            labels["confidence"] = "verified"

        if labels.get("workstream") is None:
            if labels.get("causal_pattern") in {
                "resource_leak",
                "missing_validation",
                "race_condition",
                "config_conflict",
                "state_desync",
                "dependency_break",
                "auth_failure",
                "silent_error",
                "interface_mismatch",
                "hidden_coupling",
                "observability_gap",
                "data_quality_issue",
            }:
                labels["workstream"] = "debugging"
            elif re.search(r"\bfeature\b|\bimplemented\b|\bshipped\b|\badd(?:ed)?\b", combined):
                labels["workstream"] = "feature_delivery"
            elif re.search(r"\broadmap\b|\bpricing\b|\bpositioning\b|\bpriorit", combined):
                labels["workstream"] = "product_strategy"
            elif re.search(r"\bonboarding\b|\bcopy\b|\bux\b|\busability\b|\bflow\b", combined):
                labels["workstream"] = "ux_iteration"
            elif re.search(r"\binterview\b|\bdiscovery\b|\buser research\b", combined):
                labels["workstream"] = "product_discovery"

        source_path = (source_file or "").lower()
        if ".storybook/" in source_path or source_path.endswith("/.storybook/main.js"):
            labels["workstream"] = "developer_experience"
            labels["product_surface"] = "developer_workflow"
            labels["primary_constraint"] = "delivery_speed"
            labels["decision_driver"] = labels.get("decision_driver") or "technical_constraint"
            labels["change_kind"] = labels.get("change_kind") or "improve"

        if labels.get("artifact_type") == "agent_guide":
            labels["workstream"] = labels.get("workstream") or "developer_experience"
            labels["change_kind"] = labels.get("change_kind") or "document"
            labels["resolution_strategy"] = (
                labels.get("resolution_strategy") or "document_and_enable"
            )
            labels["product_surface"] = labels.get("product_surface") or "developer_workflow"

        if labels.get("artifact_type") in {"documentation", "specification", "plan"}:
            labels["change_kind"] = labels.get("change_kind") or {
                "documentation": "document",
                "specification": "decide",
                "plan": "decide",
            }.get(labels.get("artifact_type"))

        if labels.get("change_kind") is None:
            defaults = {
                "debugging": "fix",
                "feature_delivery": "add",
                "product_discovery": "validate",
                "product_strategy": "decide",
                "ux_iteration": "redesign",
                "migration": "migrate",
                "developer_experience": "automate",
            }
            labels["change_kind"] = defaults.get(labels.get("workstream"))

        if labels.get("decision_driver") is None:
            defaults = {
                "debugging": "incident_signal",
                "product_discovery": "user_feedback",
                "product_strategy": "strategic_bet",
                "ux_iteration": "user_feedback",
                "migration": "technical_constraint",
            }
            labels["decision_driver"] = defaults.get(labels.get("workstream"))

        if labels.get("primary_constraint") is None:
            defaults = {
                "debugging": "correctness",
                "feature_delivery": "delivery_speed",
                "refactor": "maintainability",
                "architecture": "maintainability",
                "performance": "performance",
                "developer_experience": "delivery_speed",
                "product_strategy": "adoption",
                "ux_iteration": "usability",
            }
            labels["primary_constraint"] = defaults.get(labels.get("workstream"))

        if labels.get("product_surface") == "onboarding_activation":
            labels["primary_constraint"] = labels.get("primary_constraint") or "adoption"

        if labels.get("workstream") in {
            "product_strategy",
            "product_discovery",
            "ux_iteration",
        } and labels.get("severity") in {None, "minor", "major", "degradation"}:
            labels["severity"] = "opportunity"

        if labels.get("severity") is None:
            labels["severity"] = "degradation"

        return labels

    def _extract_via_llm(self, content: str) -> Optional[dict]:
        mode = os.environ.get("MEMPALACE_PATTERN_EXTRACTION_MODE", "auto").strip().lower()
        if mode == "heuristic":
            return None

        api_key = os.environ.get("MEMPALACE_PATTERN_LLM_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        model = os.environ.get("MEMPALACE_PATTERN_LLM_MODEL") or os.environ.get("OPENAI_MODEL")
        url = os.environ.get("MEMPALACE_PATTERN_LLM_URL") or os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )

        if not api_key or not model:
            return None

        if url.rstrip("/").endswith("/v1"):
            url = f"{url.rstrip('/')}/chat/completions"

        payload = {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "Classify engineering, product, and delivery episodes into a fixed taxonomy. Return JSON only.",
                },
                {"role": "user", "content": build_extraction_prompt(content, self.taxonomy)},
            ],
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None

        try:
            content_text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

        parsed = _extract_json_object(content_text)
        return self._coerce_labels(parsed or {}) if parsed else None


class PatternLabelStore:
    """Persist structural labels in a dedicated local SQLite database."""

    def __init__(self, db_path: str, taxonomy: dict = None):
        self.db_path = db_path
        self.taxonomy = deepcopy(taxonomy or PATTERN_TAXONOMY)
        self.dimensions = tuple(self.taxonomy.keys())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = None
        self._init_db()

    @classmethod
    def for_palace(cls, palace_path: str) -> "PatternLabelStore":
        return cls(os.path.join(palace_path, "pattern_labels.sqlite3"))

    def _conn(self):
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL")
        return self._connection

    def _table_columns(self) -> set[str]:
        rows = self._conn().execute("PRAGMA table_info(pattern_labels)").fetchall()
        return {row["name"] for row in rows}

    def _init_db(self):
        conn = self._conn()
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS pattern_labels (
                episode_id TEXT PRIMARY KEY,
                extracted_at TEXT NOT NULL,
                source_wing TEXT,
                source_room TEXT
            );
            """
        )

        existing_columns = self._table_columns()
        for dimension in self.dimensions:
            if dimension not in existing_columns:
                conn.execute(f"ALTER TABLE pattern_labels ADD COLUMN {dimension} TEXT")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pattern_labels_source_wing_room ON pattern_labels(source_wing, source_room)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pattern_labels_extracted_at ON pattern_labels(extracted_at DESC)"
        )
        for dimension in self.dimensions:
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_pattern_labels_{dimension} ON pattern_labels({dimension})"
            )
        conn.commit()

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def upsert_labels(
        self,
        episode_id: str,
        labels: dict,
        source_wing: str = None,
        source_room: str = None,
        extracted_at: str = None,
    ) -> dict:
        conn = self._conn()
        payload = {dimension: labels.get(dimension) for dimension in self.dimensions}
        extracted_at = extracted_at or datetime.now().isoformat()

        columns = ["episode_id", *self.dimensions, "extracted_at", "source_wing", "source_room"]
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns[1:])
        values = [
            episode_id,
            *[payload[dimension] for dimension in self.dimensions],
            extracted_at,
            source_wing,
            source_room,
        ]

        with conn:
            conn.execute(
                f"INSERT INTO pattern_labels ({', '.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT(episode_id) DO UPDATE SET {updates}",
                values,
            )
        return self.get_labels(episode_id)

    def get_labels(self, episode_id: str) -> Optional[dict]:
        row = (
            self._conn()
            .execute("SELECT * FROM pattern_labels WHERE episode_id = ?", (episode_id,))
            .fetchone()
        )
        if row is None:
            return None
        return dict(row)

    def has_labels(self, episode_id: str) -> bool:
        row = (
            self._conn()
            .execute("SELECT 1 FROM pattern_labels WHERE episode_id = ?", (episode_id,))
            .fetchone()
        )
        return row is not None

    def delete_labels(self, episode_id: str):
        with self._conn():
            self._conn().execute("DELETE FROM pattern_labels WHERE episode_id = ?", (episode_id,))

    def search(self, limit: int = 10, **filters) -> list[dict]:
        clauses = []
        params = []

        for key in (*self.dimensions, "source_wing", "source_room"):
            value = filters.get(key)
            if not value:
                continue
            clauses.append(f"{key} = ?")
            params.append(_normalize_label(value) if key in self.dimensions else value)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM pattern_labels {where} ORDER BY extracted_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn().execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def list_patterns(self, dimension: str = None) -> dict:
        requested_dimension = _normalize_dimension_name(dimension) if dimension else None
        dimensions = [requested_dimension] if requested_dimension else list(self.dimensions)
        data = {}
        conn = self._conn()

        for current_dimension in dimensions:
            if current_dimension not in self.dimensions:
                raise ValueError(f"Unknown pattern dimension: {dimension}")
            rows = conn.execute(
                f"SELECT {current_dimension} AS value, COUNT(*) AS count "
                f"FROM pattern_labels WHERE {current_dimension} IS NOT NULL AND {current_dimension} != '' "
                f"GROUP BY {current_dimension} ORDER BY count DESC, value ASC"
            ).fetchall()
            data[current_dimension] = [dict(row) for row in rows]

        total = conn.execute("SELECT COUNT(*) AS count FROM pattern_labels").fetchone()["count"]
        return {"episodes_labeled": total, "dimensions": data}


def extract_and_store_labels(
    store: PatternLabelStore,
    extractor: PatternExtractor,
    episode_id: str,
    content: str,
    metadata: dict = None,
) -> dict:
    metadata = metadata or {}
    if should_skip_pattern_labeling(metadata.get("source_file"), metadata.get("room")):
        store.delete_labels(episode_id)
        return {"labels": {}, "source": "skipped", "record": None, "skipped": True}

    extracted = extractor.extract(
        content,
        wing=metadata.get("wing"),
        room=metadata.get("room"),
        source_file=metadata.get("source_file"),
    )
    record = store.upsert_labels(
        episode_id=episode_id,
        labels=extracted["labels"],
        source_wing=metadata.get("wing"),
        source_room=metadata.get("room"),
    )
    return {
        "labels": extracted["labels"],
        "source": extracted["source"],
        "record": record,
        "skipped": False,
    }


def fetch_drawer(collection, drawer_id: str) -> Optional[dict]:
    result = collection.get(ids=[drawer_id], include=["documents", "metadatas"])
    ids = result.get("ids") or []
    if not ids:
        return None
    return {
        "id": ids[0],
        "content": result.get("documents", [""])[0],
        "metadata": result.get("metadatas", [{}])[0],
    }


def backfill_patterns(palace_path: str, limit: int = 0, reextract: bool = False) -> dict:
    client = chromadb.PersistentClient(path=palace_path)
    collection = client.get_collection("mempalace_drawers")

    store = PatternLabelStore.for_palace(palace_path)
    extractor = PatternExtractor()

    processed = 0
    labeled = 0
    skipped = 0
    skipped_low_signal = 0
    offset = 0
    batch_size = 200

    while True:
        batch = collection.get(limit=batch_size, offset=offset, include=["documents", "metadatas"])
        ids = batch.get("ids", [])
        if not ids:
            break

        for drawer_id, content, metadata in zip(
            ids,
            batch.get("documents", []),
            batch.get("metadatas", []),
        ):
            if limit and processed >= limit:
                break
            processed += 1
            if not reextract and store.has_labels(drawer_id):
                skipped += 1
                continue
            result = extract_and_store_labels(store, extractor, drawer_id, content, metadata)
            if result.get("skipped"):
                skipped_low_signal += 1
                continue
            labeled += 1

        if limit and processed >= limit:
            break
        offset += len(ids)
        if len(ids) < batch_size:
            break

    store.close()
    return {
        "palace_path": palace_path,
        "processed": processed,
        "labeled": labeled,
        "skipped": skipped,
        "skipped_low_signal": skipped_low_signal,
        "reextract": reextract,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill structural pattern labels")
    parser.add_argument(
        "--palace",
        default=os.environ.get("MEMPALACE_PALACE_PATH")
        or os.path.expanduser("~/.mempalace/palace"),
        help="Path to the MemPalace data directory",
    )
    parser.add_argument("--limit", type=int, default=0, help="Only label the first N drawers")
    parser.add_argument(
        "--reextract",
        action="store_true",
        help="Recompute labels even when a drawer already has pattern labels",
    )
    args = parser.parse_args()

    try:
        result = backfill_patterns(args.palace, limit=args.limit, reextract=args.reextract)
    except Exception as exc:
        print(f"Pattern backfill failed: {exc}")
        return 1

    print("Pattern backfill complete:")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
