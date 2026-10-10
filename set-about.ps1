$desc = @'
A DSH PreToolUse decision gate: asks five yes/no questions about every shell tool call, then allows, asks, or denies it. Swappable judge backend (TypeSafe's calibrated noul scale, or the session's own LLM), path-scoped exemption, JSONL decision log, and a pre-authorized list for irreversible steps you have already approved.
'@

gh repo edit SeasonTemple/dsh-decision-gate `
  --description $desc.Trim() `
  --add-topic dsh `
  --add-topic deepseek `
  --add-topic plugin `
  --add-topic ai-safety `
  --add-topic pre-tool-use `
  --add-topic typescript `
  --add-topic python

Write-Output '--- result ---'
gh repo view SeasonTemple/dsh-decision-gate --json description,repositoryTopics
