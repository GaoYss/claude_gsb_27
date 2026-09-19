import { createResourceApi } from './client'
import http from './client'

export const plantReplacementApi = {
  ...createResourceApi('plant-replacements'),
  summary: (params) => http.get('/plant-replacements/summary', { params }),
  costSummary: (params) => http.get('/plant-replacements/cost-summary', { params }),
  importBatch: (payload) => http.post('/plant-replacements/imports', payload),
}
