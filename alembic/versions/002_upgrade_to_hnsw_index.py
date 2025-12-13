"""Upgrade vector index from IVFFlat to HNSW for better performance

Revision ID: 002
Revises: 001
Create Date: 2025-01-21 00:00:00.000000

HNSW (Hierarchical Navigable Small World) provides:
- 2-3x faster query performance vs IVFFlat
- Better scalability with large datasets
- More accurate approximate nearest neighbor search
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old IVFFlat index
    op.execute('DROP INDEX IF EXISTS idx_markets_embedding')

    # Create HNSW index for faster vector similarity search
    # m=16: controls max connections per layer (higher = better recall, more memory)
    # ef_construction=64: search depth during construction (higher = better quality, slower build)
    op.execute('''
        CREATE INDEX idx_markets_embedding
        ON markets
        USING hnsw (text_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    ''')


def downgrade() -> None:
    # Drop HNSW index
    op.execute('DROP INDEX IF EXISTS idx_markets_embedding')

    # Restore IVFFlat index
    op.execute('''
        CREATE INDEX idx_markets_embedding
        ON markets
        USING ivfflat (text_embedding vector_cosine_ops)
    ''')
