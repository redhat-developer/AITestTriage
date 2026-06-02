from typing import List, Optional
from utils.storage import storage_client
from config.settings import settings


# =============================================================================
# CONSTANTS - Output format templates and rules
# =============================================================================

JIRA_BROWSE_URL = settings.jira_server_url.rstrip("/") + "/browse"

TEST_CASE_FORMAT = f"""*[Number]. Test Case: [Full Test Case Name]*

• *Failure Message:* `[Exact error message from JUnit XML]`
• *Root Cause Analysis:* [Insert the exact output from analyze_screenshot — a 1-2 sentence paragraph]
• *Suggested Fix:* [One concise, actionable fix]
• *Similar Jira Issues:* [max 2 issues, open issues prioritized]
  - [🔴 or 🟢] *<{JIRA_BROWSE_URL}/ISSUE-KEY|ISSUE-KEY>:* "[Issue summary]" - [Brief relevance explanation]"""

CI_FAILURE_FORMAT = f"""*[Number]. Issue Type: [CI Failure/Build Failure/Pod Log Issue]*

• *Issue Description:* [One sentence summary of the problem]
• *Failure Details:* [Key error messages and symptoms — use backticks for error text]
• *Root Cause Analysis:* [1-2 sentence analysis identifying the specific cause]
• *Suggested Fix:* [One concise, actionable fix]
• *Similar Jira Issues:* [max 2 issues, open issues prioritized]
  - [🔴 or 🟢] *<{JIRA_BROWSE_URL}/ISSUE-KEY|ISSUE-KEY>:* "[Issue summary]" - [Brief relevance explanation]"""

FORMATTING_RULES = f"""**Formatting Rules:**
1. Use Slack mrkdwn: `*bold*`, backticks for code, `•` for bullets, `-` for sub-items
2. The output from `analyze_screenshot` is a complete paragraph — insert it directly after "Root Cause Analysis:" without modification
3. For "Similar Jira Issues": you MUST call `search_similar_jira_issues` first, then format results. NEVER invent Jira issue IDs.
4. Format Jira links as: *<{JIRA_BROWSE_URL}/ISSUE-KEY|ISSUE-KEY>:* "[Summary]"
5. If `search_similar_jira_issues` returns no results, write: "No similar Jira issues found in the database."
6. "Suggested Fix" must be a single concise sentence — no numbered lists"""


class E2ETestAnalysisBuilder:
    """Builder class for creating E2E test analysis prompts."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.job_name = self._extract_job_name()

    def _extract_job_name(self) -> str:
        return self.base_dir.split("/")[1]

    # =========================================================================
    # Directory discovery (minimal — just find key paths)
    # =========================================================================

    def _get_e2e_job_directory(self) -> Optional[str]:
        artifacts_path = f"{self.base_dir}/artifacts/"
        directories = storage_client.get_immediate_directories(artifacts_path)
        e2e_dirs = [d for d in directories if d.startswith("e2e-")]
        return e2e_dirs[0] if e2e_dirs else None

    def _get_e2e_step_registry_directory(self, e2e_job_dir: str) -> Optional[str]:
        step_path = f"{self.base_dir}/artifacts/{e2e_job_dir}/"
        directories = storage_client.get_immediate_directories(step_path)
        nightly_dirs = [d for d in directories if d.endswith("-nightly")]
        return nightly_dirs[0] if nightly_dirs else None

    def _get_playwright_project_directories(self, e2e_job_dir: str, e2e_step_registry_dir: str) -> List[str]:
        artifacts_path = f"{self.base_dir}/artifacts/{e2e_job_dir}/{e2e_step_registry_dir}/artifacts/"
        directories = storage_client.get_immediate_directories(artifacts_path)
        return [d for d in directories if "reporting" not in d]

    def _get_build_log_path(self, e2e_job_dir: str, e2e_step_registry_dir: str) -> str:
        return f"{self.base_dir}/artifacts/{e2e_job_dir}/{e2e_step_registry_dir}/build-log.txt"

    # =========================================================================
    # Prompt builders
    # =========================================================================

    def _build_step_registry_failure_prompt(self, e2e_job_dir: str) -> str:
        """Build prompt when the CI job failed before reaching the test step."""
        main_build_log = f"{self.base_dir}/build-log.txt"
        all_step_dirs = storage_client.get_immediate_directories(f"{self.base_dir}/artifacts/{e2e_job_dir}/")
        step_log_paths = []
        for step_dir in all_step_dirs:
            log_path = f"{self.base_dir}/artifacts/{e2e_job_dir}/{step_dir}/build-log.txt"
            if storage_client.blob_exists(log_path):
                step_log_paths.append(f"  - {step_dir}: {log_path}")

        step_list = "\n".join(step_log_paths) if step_log_paths else "  (no build logs found)"
        prow_link = f"https://prow.ci.openshift.org/view/gs/test-platform-results/{self.base_dir}"

        return f"""You are an AI expert analyzing OpenShift CI job failures.

Prow link: {prow_link}

The CI job failed during the step registry phase — tests never ran.

Main build log (CI orchestrator): `{main_build_log}`

Step directories with build logs:
{step_list}

**Analysis Strategy:**
1. **ALWAYS read the main build log first** using `read_file("{main_build_log}")` — this contains the orchestration-level root cause (pod failures, resource errors, scheduling issues)
2. Read step build logs only if needed for additional detail
3. For each failure, search for similar JIRA issues (`search_similar_jira_issues`)
4. Report using the CI failure format below

{CI_FAILURE_FORMAT}

{FORMATTING_RULES}

Start your analysis."""

    def _build_analysis_prompt(self, e2e_job_dir: str, e2e_step_registry_dir: str,
                               project_dirs: List[str], build_log_path: str) -> str:
        """Build the strategic analysis prompt."""
        artifacts_base = f"{self.base_dir}/artifacts/{e2e_job_dir}/{e2e_step_registry_dir}/artifacts"
        prow_link = f"https://prow.ci.openshift.org/view/gs/test-platform-results/{self.base_dir}"

        project_entries = []
        for d in project_dirs:
            project_entries.append(f"  - {d}/  (artifacts at: {artifacts_base}/{d}/)")
        project_list = "\n".join(project_entries)

        return f"""You are an AI expert analyzing Playwright E2E test failures from OpenShift CI.
You MUST use the provided tools to gather information — do NOT assume any content is pre-loaded.

Prow link: {prow_link}

## Artifact Layout

All paths are in GCS bucket `test-platform-results`.

Build log: `{build_log_path}`

Projects:
{project_list}

Each project directory may contain:
- `junit-results.xml` — Playwright test results
- `test-results/` — failure screenshots (path referenced in junit XML)
- `pod_logs/` — container logs from test infrastructure pods

## Analysis Strategy

1. **ALWAYS read the build log first** using `read_file("{build_log_path}")`.
   Look for deployment failures, operator errors, ingress issues, image pull problems,
   or any infrastructure-level errors. This often reveals the root cause when tests
   didn't execute.

2. **For each project** ({', '.join(project_dirs)}):
   a. Check if `junit-results.xml` exists using `file_exists`
   b. **If it exists** (test failures):
      - Parse failures with `parse_junit_failures`
      - For EACH failure: call `analyze_screenshot` with the screenshot path
        (construct by joining the project's `test-results/` path with the relative
        path from the junit XML)
      - For EACH failure: call `search_similar_jira_issues` — NEVER invent issue IDs
   c. **If it does NOT exist** (tests never ran):
      - Check for `pod_logs/` using `list_directories`
      - If found, read pod logs with `read_log_files`
      - Cross-reference pod logs with build log findings
      - Call `search_similar_jira_issues` for the failure

3. **Cross-failure patterns**: If multiple projects share the same root cause,
   note the pattern.

4. **JIRA creation prompt**: At the end, list failures without open JIRA issues
   and ask if the user wants to create them.

## Output Format

**For test case failures (junit XML exists):**

{TEST_CASE_FORMAT}

**For CI/infrastructure/pod log failures:**

{CI_FAILURE_FORMAT}

{FORMATTING_RULES}

**Cross-Failure Patterns:**
If 2+ failures share the same root cause, add before the JIRA creation prompt:

*Cross-Failure Patterns Detected:*
• [Pattern description] affects: [Project 1], [Project 2]

**JIRA Creation:**
After ALL analysis, if any failures lack an open JIRA issue:

---
*Would you like me to create Jira issues for the following failures which don't have open Jira issues?*
• Failure 1 [description]
• Failure 2 [description]

Start your analysis."""

    def build_prompt(self) -> str:
        """Build the complete E2E test analysis prompt."""
        e2e_job_dir = self._get_e2e_job_directory()
        if not e2e_job_dir:
            return "No E2E job directory found."

        e2e_step_registry_dir = self._get_e2e_step_registry_directory(e2e_job_dir)

        if not e2e_step_registry_dir:
            return self._build_step_registry_failure_prompt(e2e_job_dir)

        build_log_path = self._get_build_log_path(e2e_job_dir, e2e_step_registry_dir)
        project_dirs = self._get_playwright_project_directories(e2e_job_dir, e2e_step_registry_dir)

        if not project_dirs:
            # No project dirs found — fall back to build log analysis
            return self._build_analysis_prompt(e2e_job_dir, e2e_step_registry_dir, [], build_log_path)

        return self._build_analysis_prompt(e2e_job_dir, e2e_step_registry_dir, project_dirs, build_log_path)


def get_e2e_test_analysis_prompt(base_dir: str) -> str:
    """Generate E2E test analysis prompt for given base directory."""
    builder = E2ETestAnalysisBuilder(base_dir)
    return builder.build_prompt()
