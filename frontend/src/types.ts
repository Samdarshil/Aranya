export type Evidence = { description: string; source: string; confidence: number };
export type Recommendation = {
  problem: string;
  evidence: Evidence[];
  confidence: number;
  severity: string;
  urgency: string;
  recommended_action: string;
  reasoning: string;
  alternatives?: string[];
  monitoring_plan?: string | null;
  escalate_to_expert: boolean;
  escalation_reason?: string | null;
  source_agent: string;
  generated_at: string;
};
export type Alert = {
  id: number; problem: string; subject_ref?: string; severity: string;
  created_at: string; source_agent?: string;
};
export type Consultation = {
  id: number; problem: string; source_agent: string; severity: string;
  requested_at: string; escalation_reason?: string;
};
export type ChatReply = {
  type: 'clarification' | 'error' | 'recommendation' | 'history' | 'answer';
  message?: string; what_happened?: string; what_to_do?: string;
  why_it_matters?: string; evidence?: string[]; confidence_pct?: number;
  how_urgent?: string; ask_an_expert?: boolean; escalation_reason?: string;
  source_agent?: string;
  transcript?: string; detected_language?: string; audio_reply_available?: boolean;
  audio_reply_base64?: string;
  scan_count?: number; latest_status?: string; latest_risk_level?: string;
  latest_timestamp?: string;
};
