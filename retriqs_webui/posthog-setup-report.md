# PostHog post-wizard report

The wizard has completed a deep integration of PostHog analytics into Retriqs. The existing `src/lib/analytics.ts` wrapper (using `posthog-js`) was already in place but had no callsites — the wizard wired up all event tracking, user identification, error capture, and a PostHog dashboard with 5 insights.

**Changes made:**
- `posthog-js` added to `package.json` dependencies (was in `node_modules` but not declared)
- `.env` populated with `VITE_PUBLIC_POSTHOG_KEY` and `VITE_PUBLIC_POSTHOG_HOST`
- `captureException` export added to `src/lib/analytics.ts`
- 7 source files instrumented with `trackEvent`, `identifyAnalyticsUser`, `resetAnalytics`, and `captureException` calls

| Event | Description | File |
|-------|-------------|------|
| `user_logged_in` | User successfully authenticates (password or guest mode). Also calls `identifyAnalyticsUser`. | `src/features/LoginPage.tsx` |
| `user_logged_out` | User clicks the logout button. Also calls `resetAnalytics` to clear identity. | `src/features/SiteHeader.tsx` |
| `document_upload_started` | Batch upload initiated (file count, tenant context). | `src/components/documents/UploadDocumentsDialog.tsx` |
| `document_upload_completed` | Individual file uploaded successfully (file name, size). | `src/components/documents/UploadDocumentsDialog.tsx` |
| `document_upload_failed` | File upload failed (error code/message). | `src/components/documents/UploadDocumentsDialog.tsx` |
| `documents_deleted` | User confirmed deletion of selected documents (count, delete-file flag). | `src/components/documents/DeleteDocumentsDialog.tsx` |
| `documents_cleared` | User confirmed clearing the entire knowledge base. | `src/components/documents/ClearDocumentsDialog.tsx` |
| `query_started` | Retrieval query submitted (mode, streaming, query length, workspace). | `src/features/RetrievalTesting.tsx` |
| `query_completed` | Query response received successfully. | `src/features/RetrievalTesting.tsx` |
| `query_failed` | Query returned an error. Also acts as error tracking for the retrieval flow. | `src/features/RetrievalTesting.tsx` |
| `chat_created` | New chat session created in the retrieval panel. | `src/features/RetrievalTesting.tsx` |
| `chat_deleted` | Chat session deleted from the retrieval panel. | `src/features/RetrievalTesting.tsx` |
| `graph_node_selected` | User selects a node via the knowledge graph search bar. | `src/features/GraphViewer.tsx` |

**Error tracking:** `captureException` is called in the login error handler (`src/features/LoginPage.tsx`). Query errors are tracked via the `query_failed` event with full error details.

## Next steps

We've built some insights and a dashboard for you to keep an eye on user behavior, based on the events we just instrumented:

- **Dashboard — Analytics basics:** https://eu.posthog.com/project/157408/dashboard/615859
- **Daily Active Users (Logins):** https://eu.posthog.com/project/157408/insights/GfLuwFpo
- **Document Operations:** https://eu.posthog.com/project/157408/insights/jEsPUuHZ
- **Login → Query → Upload Funnel:** https://eu.posthog.com/project/157408/insights/8EQy3PHS
- **Query Volume by Mode:** https://eu.posthog.com/project/157408/insights/NC5nNB8I
- **Feature Engagement Overview:** https://eu.posthog.com/project/157408/insights/xnvTSXzW

### Agent skill

We've left an agent skill folder in your project. You can use this context for further agent development when using Claude Code. This will help ensure the model provides the most up-to-date approaches for integrating PostHog.
