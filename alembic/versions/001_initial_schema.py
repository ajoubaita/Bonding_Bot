"""Initial schema with pgvector extension

Revision ID: 001
Revises:
Create Date: 2025-01-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create markets table
    op.create_table(
        'markets',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('condition_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('raw_title', sa.Text(), nullable=True),
        sa.Column('raw_description', sa.Text(), nullable=True),
        sa.Column('clean_title', sa.Text(), nullable=True),
        sa.Column('clean_description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('event_type', sa.String(), nullable=True),
        sa.Column('entities', JSONB, nullable=True),
        sa.Column('geo_scope', sa.String(), nullable=True),
        sa.Column('time_window', JSONB, nullable=True),
        sa.Column('resolution_source', sa.String(), nullable=True),
        sa.Column('outcome_schema', JSONB, nullable=True),
        sa.Column('text_embedding', sa.String(), nullable=True),  # Will be vector(384)
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for markets
    op.create_index('idx_markets_platform', 'markets', ['platform'])
    op.create_index('idx_markets_category', 'markets', ['category'])
    op.create_index('idx_markets_status', 'markets', ['status'])
    op.create_index('idx_markets_condition_id', 'markets', ['condition_id'])

    # Alter text_embedding column to use vector type
    op.execute('ALTER TABLE markets ALTER COLUMN text_embedding TYPE vector(384) USING text_embedding::vector')

    # Create vector similarity index using ivfflat
    # Note: This requires some data in the table first for proper clustering
    # In production, run this after ingesting initial markets:
    # CREATE INDEX idx_markets_embedding ON markets USING ivfflat (text_embedding vector_cosine_ops) WITH (lists = 100);
    # For now, we'll create a basic index
    op.execute('CREATE INDEX idx_markets_embedding ON markets USING ivfflat (text_embedding vector_cosine_ops)')

    # Create bonds table
    op.create_table(
        'bonds',
        sa.Column('pair_id', sa.String(), nullable=False),
        sa.Column('kalshi_market_id', sa.String(), nullable=False),
        sa.Column('polymarket_market_id', sa.String(), nullable=False),
        sa.Column('tier', sa.Integer(), nullable=False),
        sa.Column('p_match', sa.Float(), nullable=False),
        sa.Column('similarity_score', sa.Float(), nullable=False),
        sa.Column('outcome_mapping', JSONB, nullable=False),
        sa.Column('feature_breakdown', JSONB, nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_validated', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('pair_id'),
        sa.ForeignKeyConstraint(['kalshi_market_id'], ['markets.id']),
        sa.ForeignKeyConstraint(['polymarket_market_id'], ['markets.id']),
        sa.CheckConstraint('tier IN (1, 2, 3)', name='bonds_tier_check')
    )

    # Create indexes for bonds
    op.create_index('idx_bonds_tier', 'bonds', ['tier'])
    op.create_index('idx_bonds_status', 'bonds', ['status'])
    op.create_index('idx_bonds_kalshi', 'bonds', ['kalshi_market_id'])
    op.create_index('idx_bonds_poly', 'bonds', ['polymarket_market_id'])
    op.create_index('idx_bonds_active_tier', 'bonds', ['tier', 'status'])


def downgrade() -> None:
    # Drop tables
    op.drop_table('bonds')
    op.drop_table('markets')

    # Drop pgvector extension
    op.execute('DROP EXTENSION IF EXISTS vector')
