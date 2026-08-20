from models.member import MemberCreate


def test_membership_id_is_not_accepting_user_input():
    assert "membership_id" not in MemberCreate.model_fields
