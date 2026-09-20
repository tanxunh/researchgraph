import { useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { libraryApi } from '../api/library';
import { useResource } from './useResource';

export function useReadyDocuments() {
  const { key: routeEntry } = useLocation();
  const load = useCallback(signal => libraryApi.documents({ signal }), [routeEntry]);
  return useResource(load, undefined, true);
}
