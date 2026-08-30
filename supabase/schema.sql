-- ==============================================================================
-- lifeOS Supabase Schema Migration (with RLS + Realtime)
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

-- Indexes for lightning fast queries
CREATE INDEX IF NOT EXISTS idx_routine_tasks_user_pos ON public.routine_tasks(user_id, position);
CREATE INDEX IF NOT EXISTS idx_completions_user_date ON public.completions(user_id, date);
CREATE INDEX IF NOT EXISTS idx_completions_task_date ON public.completions(task_id, date);
CREATE INDEX IF NOT EXISTS idx_journal_entries_user_date ON public.journal_entries(user_id, date);

-- ------------------------------------------------------------------------------
-- Row Level Security (RLS) Policies
-- ------------------------------------------------------------------------------
ALTER TABLE public.routine_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.completions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.journal_entries ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to manage their own rows
CREATE POLICY "Users can manage their own routine_tasks"
    ON public.routine_tasks
    FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can manage their own completions"
    ON public.completions
    FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can manage their own journal_entries"
    ON public.journal_entries
    FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Also support single-user / anon key access when run locally with public anon key
CREATE POLICY "Anon key access for single-user routine_tasks"
    ON public.routine_tasks
    FOR ALL
    TO anon
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Anon key access for single-user completions"
    ON public.completions
    FOR ALL
    TO anon
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Anon key access for single-user journal_entries"
    ON public.journal_entries
    FOR ALL
    TO anon
    USING (true)
    WITH CHECK (true);

-- ------------------------------------------------------------------------------
-- Realtime Publication
-- ------------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables 
        WHERE pubname = 'supabase_realtime' AND tablename = 'routine_tasks'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.routine_tasks;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables 
        WHERE pubname = 'supabase_realtime' AND tablename = 'completions'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.completions;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables 
        WHERE pubname = 'supabase_realtime' AND tablename = 'journal_entries'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.journal_entries;
    END IF;
END $$;
