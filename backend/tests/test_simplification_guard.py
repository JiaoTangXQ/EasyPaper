from app.services.simplification_guard import guarded_simplification, keep_source_label


def test_title_expansion_and_placeholder_acknowledgement_cannot_cover_the_page():
    title = "Repo-To-Skill: Distilling GitHub Repositories Into AI4AI Skills"
    assert keep_source_label(title)
    assert guarded_simplification(title, "This paper presents a new method. " * 30) == title
    assert guarded_simplification("{v0}", "I'm ready to help simplify academic English.") == "{v0}"


def test_real_paragraph_rewrite_preserves_numbers_and_formula_placeholders():
    source = "The method utilizes 20 specialized tools and reduces memory usage by 30% {v2}."
    valid = "The method uses 20 special tools and needs 30% less memory {v2}."
    assert guarded_simplification(source, valid) == valid
    assert guarded_simplification(source, valid.replace("30%", "50%")) == source
    assert guarded_simplification(source, valid.replace("{v2}", "")) == source
