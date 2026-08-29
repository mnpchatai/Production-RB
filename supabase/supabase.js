// Production RB: lightweight Supabase client adapter
// Usage:
// 1) npm install @supabase/supabase-js
// 2) paste your Supabase URL and anon key below
// 3) replace localStorage save/load calls in index.html with these helpers

const supabaseUrl = 'https://YOUR_PROJECT_REF.supabase.co';
const supabaseAnonKey = 'YOUR_ANON_KEY';

export const supabase = globalThis.supabase ?? null;

if (typeof window !== 'undefined' && !globalThis.supabase) {
  try {
    const { createClient } = await import('@supabase/supabase-js');
    globalThis.supabase = createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    });
  } catch (error) {
    console.warn('Supabase client not initialized:', error);
  }
}

export async function loadFromSupabase(table) {
  if (!supabase) return [];
  const { data, error } = await supabase.from(table).select('*');
  if (error) {
    console.error('loadFromSupabase error:', error);
    return [];
  }
  return data || [];
}

export async function saveToSupabase(table, rows, mode = 'upsert') {
  if (!supabase || !rows || rows.length === 0) return { data: [], error: null };
  const { data, error } = mode === 'insert'
    ? await supabase.from(table).insert(rows)
    : await supabase.from(table).upsert(rows, { onConflict: 'id' });

  if (error) {
    console.error('saveToSupabase error:', error);
  }

  return { data: data || [], error };
}

export async function getSettings() {
  const rows = await loadFromSupabase('settings');
  return Object.fromEntries((rows || []).map(r => [r.key, r.value]));
}

export async function setSetting(key, value) {
  if (!supabase) return;
  await supabase.from('settings').upsert({ key, value }, { onConflict: 'key' });
}
