"""NanoSchool lab sessions: accounts come from the hub, and passwords go away

A session now exists only because live-labs.org verified a launch, so the users
table records which hub account a row is, and stops storing a credential this
lab no longer accepts. Existing rows keep their runs and reports; they simply
have no hub id until that person launches the lab, at which point the account
is matched by email and linked.

Revision ID: b41f7c2ad9e3
Revises: fc6dd0e7071f
Created: 2026-09-12 11:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b41f7c2ad9e3'
down_revision: Union[str, None] = 'fc6dd0e7071f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hub_user_id', sa.String(length=64), nullable=True))
        # Existing rows predate the flag; the hub sets it on the next launch.
        batch_op.add_column(
            sa.Column(
                'is_reviewer', sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.create_index(
            batch_op.f('ix_users_hub_user_id'), ['hub_user_id'], unique=True
        )
        batch_op.drop_column('password_hash')


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        # Nullable on the way back: the hashes are gone, and inventing one that
        # nothing can verify would be worse than a column that says "no
        # password". Restoring password sign-in needs a deliberate reset, not a
        # downgrade.
        batch_op.add_column(sa.Column('password_hash', sa.String(length=255), nullable=True))
        batch_op.drop_index(batch_op.f('ix_users_hub_user_id'))
        batch_op.drop_column('is_reviewer')
        batch_op.drop_column('hub_user_id')
