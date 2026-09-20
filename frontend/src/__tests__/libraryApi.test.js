import { it,expect,vi } from 'vitest';
import { libraryApi } from '../api/library';
import { apiClient } from '../api/client';
vi.mock('../api/client',()=>({apiClient:{get:vi.fn(),post:vi.fn()}}));
it('async upload uses multipart and only public endpoints',async()=>{
 const file=new File(['paper'],'sample.pdf');await libraryApi.upload(file);
 expect(apiClient.post.mock.calls[0][0]).toBe('/api/documents/import/file/async');expect(apiClient.post.mock.calls[0][1].get('file')).toBe(file);
 await libraryApi.job(7);expect(apiClient.get).toHaveBeenLastCalledWith('/api/index-jobs/7',undefined);
 await libraryApi.retry(7);expect(apiClient.post).toHaveBeenLastCalledWith('/api/index-jobs/7/retry');
});
