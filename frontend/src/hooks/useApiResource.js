import { useCallback, useEffect, useState } from 'react';

// Shared shape for every data-fetching hook in the app:
//   { status: 'loading' | 'success' | 'error', data, error, refetch }
// `status` is what components branch on for the loading/error/empty triad —
// "empty" is a component-level judgment on `data`, not a fourth status.
export function useApiResource(fetchFn, deps = []) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null });

  const run = useCallback(() => {
    let cancelled = false;
    setState((s) => ({ ...s, status: 'loading', error: null }));

    fetchFn()
      .then((data) => {
        if (!cancelled) setState({ status: 'success', data, error: null });
      })
      .catch((error) => {
        if (!cancelled) setState({ status: 'error', data: null, error });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => run(), [run]);

  return { ...state, refetch: run };
}
