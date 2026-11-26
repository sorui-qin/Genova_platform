"""Grant or revoke an existing account's admin role from the deployment shell."""
import argparse
from uuid import UUID

from sqlalchemy import select
from backend.db import SessionLocal
from backend.models import User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['grant', 'revoke'])
    parser.add_argument('user_id', type=UUID)
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == args.user_id).with_for_update())
        if user is None or user.is_guest or not user.is_active:
            parser.error('Choose an existing active registered account')
        user.is_admin = args.action == 'grant'
        db.commit()
        print(f'{args.action}: {user.id}')


if __name__ == '__main__':
    main()
