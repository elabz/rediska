export interface Counterpart {
  id: number;
  external_username: string;
  external_user_id: string | null;
  remote_status: string;
  is_starred: boolean;
}

export interface ConversationDetail {
  id: number;
  provider_id: string;
  identity_id: number;
  external_conversation_id: string;
  counterpart: Counterpart;
  last_activity_at: string | null;
  counterpart_last_post_title: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Attachment {
  id: number;
  mime_type: string;
  size_bytes: number;
  width_px: number | null;
  height_px: number | null;
}

export interface Message {
  id: number;
  direction: 'in' | 'out' | 'system';
  body_text: string | null;
  sent_at: string;
  remote_visibility: string;
  send_error: string | null;
  identity_id: number | null;
  external_message_id?: string | null;
  created_at: string;
  attachments?: Attachment[];
}

export interface MessagesResponse {
  messages: Message[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface GalleryImage {
  attachment: Attachment;
  messageId: number;
  sentAt: string;
}

export interface ListSummary {
  id: number;
  name: string;
  conversation_count: number;
}
