-- ==============================================================================
-- lifeOS v3 Execution Operating System — Supabase Schema Migration
-- ==============================================================================

-- Enable UUID extension if not already present
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. routine_tasks
CREATE TABLE IF NOT EXISTS public.routine_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    position INT NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. completions
CREATE TABLE IF NOT EXISTS public.completions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    task_id UUID NOT NULL REFERENCES public.routine_tasks(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    done BOOLEAN NOT NULL DEFAULT TRUE,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT completions_user_task_date_key UNIQUE (user_id, task_id, date)
);

-- 3. journal_entries
CREATE TABLE IF NOT EXISTS public.journal_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    word_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT journal_entries_user_date_key UNIQUE (user_id, date)
);

-- 4. projects
CREATE TABLE IF NOT EXISTS public.projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    area TEXT NOT NULL DEFAULT 'Career',
    status TEXT NOT NULL DEFAULT 'active',
    outcome TEXT NOT NULL DEFAULT '',
    deadline DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ
);

-- 5. actions
CREATE TABLE IF NOT EXISTS public.actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    project_id UUID REFERENCES public.projects(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'next',
    estimate_minutes INT NOT NULL DEFAULT 30,
    energy_level TEXT NOT NULL DEFAULT 'medium',
    context TEXT NOT NULL DEFAULT 'desk',
    due_date DATE,
    scheduled_date DATE,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. action_dependencies
CREATE TABLE IF NOT EXISTS public.action_dependencies (
    action_id UUID NOT NULL REFERENCES public.actions(id) ON DELETE CASCADE,
    blocked_by_action_id UUID NOT NULL REFERENCES public.actions(id) ON DELETE CASCADE,
    PRIMARY KEY (action_id, blocked_by_action_id)
);

-- 7. daily_priorities
CREATE TABLE IF NOT EXISTS public.daily_priorities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    action_id UUID NOT NULL REFERENCES public.actions(id) ON DELETE CASCADE,
    rank INT NOT NULL CHECK(rank BETWEEN 1 AND 3),
    committed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT daily_priorities_user_date_rank_key UNIQUE (user_id, date, rank)
);

-- 8. time_blocks
CREATE TABLE IF NOT EXISTS public.time_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    action_id UUID REFERENCES public.actions(id) ON DELETE SET NULL,
    kind TEXT NOT NULL DEFAULT 'deep_work',
    planned_minutes INT NOT NULL DEFAULT 90,
    actual_minutes INT,
    status TEXT NOT NULL DEFAULT 'planned',
    notes TEXT
);

-- 9. inbox_items
CREATE TABLE IF NOT EXISTS public.inbox_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source TEXT NOT NULL DEFAULT 'quick_capture',
    status TEXT NOT NULL DEFAULT 'unprocessed',
    linked_project_id UUID REFERENCES public.projects(id) ON DELETE SET NULL,
    converted_action_id UUID REFERENCES public.actions(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ
);

-- Indexes for queries
CREATE INDEX IF NOT EXISTS idx_routine_tasks_user_pos ON public.routine_tasks(user_id, position);
CREATE INDEX IF NOT EXISTS idx_completions_user_date ON public.completions(user_id, date);
CREATE INDEX IF NOT EXISTS idx_journal_entries_user_date ON public.journal_entries(user_id, date);
CREATE INDEX IF NOT EXISTS idx_projects_user_status ON public.projects(user_id, status);
CREATE INDEX IF NOT EXISTS idx_actions_user_status ON public.actions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_actions_proj ON public.actions(project_id);
CREATE INDEX IF NOT EXISTS idx_daily_priorities_user_date ON public.daily_priorities(user_id, date);
CREATE INDEX IF NOT EXISTS idx_time_blocks_user_date ON public.time_blocks(user_id, date);
CREATE INDEX IF NOT EXISTS idx_inbox_items_user_status ON public.inbox_items(user_id, status);

-- ------------------------------------------------------------------------------
-- Row Level Security (RLS) Policies
-- ------------------------------------------------------------------------------
ALTER TABLE public.routine_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.completions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.journal_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.action_dependencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_priorities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.time_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inbox_items ENABLE ROW LEVEL SECURITY;

-- Authenticated Policies
DO $$
DECLARE
    tbl text;
BEGIN
    FOR tbl IN SELECT unnest(ARRAY['routine_tasks', 'completions', 'journal_entries', 'projects', 'actions', 'daily_priorities', 'time_blocks', 'inbox_items'])
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS "auth_all_%s" ON public.%I', tbl, tbl);
        EXECUTE format('CREATE POLICY "auth_all_%s" ON public.%I FOR ALL TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)', tbl, tbl);
        EXECUTE format('DROP POLICY IF EXISTS "anon_all_%s" ON public.%I', tbl, tbl);
        EXECUTE format('CREATE POLICY "anon_all_%s" ON public.%I FOR ALL TO anon USING (true) WITH CHECK (true)', tbl, tbl);
    END LOOP;
END $$;

-- ------------------------------------------------------------------------------
-- Realtime Publication
-- ------------------------------------------------------------------------------
DO $$
DECLARE
    tbl text;
BEGIN
    FOR tbl IN SELECT unnest(ARRAY['routine_tasks', 'completions', 'journal_entries', 'projects', 'actions', 'daily_priorities', 'time_blocks', 'inbox_items'])
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_publication_tables 
            WHERE pubname = 'supabase_realtime' AND tablename = tbl
        ) THEN
            EXECUTE format('ALTER PUBLICATION supabase_realtime ADD TABLE public.%I', tbl);
        END IF;
    END LOOP;
END $$;
