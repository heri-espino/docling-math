from docling_math.naming import infer_paper_identity


def test_spanish_hyphenated_surname():
    markdown = """---
id: "123"
---
# Estimacion de tendencia

Daniela Cortes-Toto y Heriberto Espino

Universidad de las Americas Puebla

© 2011 Journal Something

## Abstract

Contenido.
"""
    identity = infer_paper_identity(markdown)
    assert identity is not None
    assert identity.stem == "CortesToto_Espino-2011-Estimacion_de_tendencia"


def test_english_names_and_accents():
    markdown = """# A Bayesian Approach to Something

John Smith and María García-López

Department of Mathematics, University X

Published 2024

## Abstract
"""
    identity = infer_paper_identity(markdown)
    assert identity is not None
    assert identity.stem == "Smith_GarciaLopez-2024-A_Bayesian_Approach_to_Something"


def test_missing_metadata_is_conservative():
    markdown = """# A Paper With No Metadata

## Abstract

No author block or publication year is available.
"""
    assert infer_paper_identity(markdown) is None
