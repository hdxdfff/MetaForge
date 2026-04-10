# ML Binary Classification Lab Dispatch Brief

Updated: 2026-03-21
Source template: `D:\xwechat_files\wxid_wraikhyxu4wp22_ee1d\msg\file\2026-03\实验模板.docx`
Owner after dispatch: MetaForge control layer and worker system

## Extracted experiment requirements

- Build three binary classification models: logistic regression, SVM, and perceptron.
- Use SGD to solve the models.
- Measure test-set accuracy and compare the three models.
- Complete an experiment report.

## Known constraints

- The provided DOCX is only a report template.
- No explicit dataset or teacher-provided experiment package was found next to the template.
- The dispatch must not fabricate metrics if data is missing.

## Target workspace

- `D:\codex\generated\ml-binary-classification-lab`

## Required return artifact

- `D:\codex\generated\ml-binary-classification-lab\BINARY_CLASSIFICATION_AUTORUN_RESULT.md`

## Validation contract

- If a usable dataset is found locally, run the experiment and record the command plus measured accuracies.
- If no usable dataset is found, downgrade to a blocker-first result that includes:
  - the detection result,
  - exact missing inputs,
  - a ready-to-run local experiment plan,
  - a report skeleton mapped to the supplied template.

## Boundary

- Operate only on `D:\codex\generated\ml-binary-classification-lab`.
- Do not modify the control layer, factory runtime, unrelated workspaces, or the original source DOCX.

## Control tier

- `chore-only`
