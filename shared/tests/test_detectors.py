from rddc_screen_common.detectors import is_full_date, scan


def test_shapes_found():
    assert scan("SSN 999-60-5596") == ["ssn"]
    assert scan("call 555-786-4684 today") == ["phone"]
    assert scan("(555) 786-4684") == ["phone"]
    assert scan("j.doe@example.org") == ["email"]
    assert scan("from 10.1.2.3") == ["ipv4"]
    assert scan("MRN: 00123456") == ["mrn_label"]
    assert scan("see https://portal.example.org/p/1") == ["url"]


def test_not_identifiers():
    # dates, times, decimals, codes and UUIDs are not phone numbers or SSNs
    for text in ["2023-11-01T08:01:53-07:00", "1994-02-13", "31.514", "72166-2",
                 "bb0f1798-a377-3418-41f5-a58c8c6ed14d", "(01)56196275202964(11)940123"]:
        assert scan(text) == [], text


def test_url_hosts_allowed():
    hosts = ("www.w3.org", "github.com/synthetichealth")
    assert scan('<div xmlns="http://www.w3.org/1999/xhtml">', hosts) == []
    assert scan("https://github.com/synthetichealth/synthea", hosts) == []
    assert scan("https://github.com/someone-else", hosts) == ["url"]


def test_full_date():
    assert is_full_date("1989-11-20") and is_full_date("2023-11-01T08:01:53-07:00")
    assert not is_full_date("1989") and not is_full_date("1989-11")
