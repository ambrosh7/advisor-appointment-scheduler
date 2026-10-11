from nlu.names import extract_full_name


def test_extract_full_name_variants():
    assert extract_full_name("Ambrosh Patel") == "Ambrosh Patel"
    assert extract_full_name("my name is priya sharma") == "Priya Sharma"
    assert extract_full_name("I'm Jane Doe") == "Jane Doe"
    assert extract_full_name("yes") is None
    assert extract_full_name("Ambrosh") == "Ambrosh"
    assert extract_full_name("call me at +91 9876543210") is None
