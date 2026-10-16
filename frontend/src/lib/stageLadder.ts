/** 保留作者文字，只以约定的箭头分层。 */
export function splitStageLadder(value: string | null | undefined): string[] {
  return (value ?? '').split(/→|->|—>|＞/u).map(stage => stage.trim()).filter(Boolean)
}
