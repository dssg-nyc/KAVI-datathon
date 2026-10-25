# /// script
# requires-python = ">=3.10"
# ///
# Tests for the description-keyword tagging in scripts/pdf/extend_clean_resources.py: that it finds
# every secondary service a description names, and that those secondary services are added even to
# a row that already has a primary service type (issue #19). Run:
#
#   uv run scripts/tests/extend_clean_resources.test.py

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pdf"))
from extend_clean_resources import joined, service_types_in  # noqa: E402

# Hetrick-Martin Institute's description, quoted in issue #19: an LGBTQIA+ youth organization
# whose description names several other services it offers beyond that primary focus.
HMI_DESCRIPTION = (
    "Provides free year-round programs and services for LGBTQIA+ youth ages 13–24 and their "
    "families. Services include adult education, behavioral health, case management and service "
    "coordination, employment assistance, health information and support, HSE classes and "
    "testing, HIV/AIDS services, meals, family and group counseling, services for homeless youth, "
    "and more."
)


def test_keyword_match_finds_every_secondary_service_named_in_the_description():
    found = set(service_types_in(HMI_DESCRIPTION).split("; "))
    assert found == {"Education", "Employment", "Food", "Health & Mental Health"}, found


def test_secondary_types_are_added_even_when_a_primary_type_is_already_assigned():
    # Before issue #19's fix, extend_clean_resources.py only looked for description-keyword types
    # on rows with no service_type_extended yet, so a row's primary type (e.g. from the guide's
    # LGBTQIA+ Youth chapter) would have blocked its other services from ever reaching
    # service_types_all. This reproduces that merge directly and checks the primary type survives
    # alongside the secondary ones found in the description.
    primary_type = "Family & Childcare"
    secondary_types = service_types_in(HMI_DESCRIPTION)
    service_types_all = joined((primary_type + "; " + secondary_types).split("; "))
    assert service_types_all == "Education; Employment; Family & Childcare; Food; Health & Mental Health"


if __name__ == "__main__":
    test_keyword_match_finds_every_secondary_service_named_in_the_description()
    test_secondary_types_are_added_even_when_a_primary_type_is_already_assigned()
    print("ok")
