import rpi_mastery


def test_public_api_version_matches_release():
    assert rpi_mastery.__version__ == "0.4.0"


def test_new_release_building_blocks_are_publicly_importable():
    expected = {
        "LocalBackupManager",
        "ReloadableRuleEngine",
        "WatchdogOutput",
        "PrivacyFirstSentinel",
        "render_prometheus",
        "AuditSummary",
        "HealthTrend",
        "RuleEvaluation",
    }

    assert expected <= set(rpi_mastery.__all__)
    assert all(hasattr(rpi_mastery, name) for name in expected)
