from datetime import date

from src.agents.qualification import HPEQualificationAgent, qualify_tender
from src.schemas.common import Recommendation


def test_qualify_tender_end_to_end(sample_extracted, sample_hpe_profile):
    briefing = qualify_tender(sample_extracted, sample_hpe_profile, as_of=date(2026, 9, 18))
    assert briefing.tender.id == sample_extracted.tender.id
    assert briefing.recommendation in (Recommendation.GO, Recommendation.MAYBE, Recommendation.NO_GO)


def test_hpe_qualification_agent_class_wrapper(sample_extracted, sample_hpe_profile):
    agent = HPEQualificationAgent()
    briefing = agent.qualify_tender(sample_extracted, sample_hpe_profile, as_of=date(2026, 9, 18))
    assert briefing.recommendation is not None
