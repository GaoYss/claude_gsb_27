import { createResourceApi } from './client'
import http from './client'

export const plantReplacementApi = {
  ...createResourceApi('plant-replacements'),
  summary: (params) => http.get('/plant-replacements/summary', { params }),
  costReport: (params) => http.get('/plant-replacements/cost-report', { params }),
  importBatch: (payload) => http.post('/plant-replacements/import', payload),
}
