from database.mongodb import db_helper as db
from datetime import datetime
from bson import ObjectId

# Find the member user
user = db.users.find_one({'username': 'e2e_member_mszpw6fw'})
print('User:', user)

# Find the member profile
member = db.members.find_one({'user_id': str(user['_id'])})
print('Member profile:', member)

# If not found, create proper link
if not member:
    member = db.members.find_one({'email': 'e2e_member_mszpw6fw@test.dev'})
    if member:
        db.members.update_one({'_id': member['_id']}, {'$set': {'user_id': str(user['_id'])}})
        print('Updated member profile with user_id')
    else:
        # Create new member profile
        db.members.insert_one({
            'user_id': str(user['_id']),
            'name': 'E2E Test Member',
            'email': 'e2e_member_mszpw6fw@test.dev',
            'phone': '555-0123',
            'address': '123 Test St',
            'membership_id': 'MEM-' + str(user['_id'])[:8],
            'created_at': datetime.utcnow()
        })
        print('Created new member profile')
else:
    print('Member profile already linked')