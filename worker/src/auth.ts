const encoder = new TextEncoder();

/** 두 문자열을 길이와 내용 모두에 대해 일정한 반복 횟수로 비교한다. */
export function constantTimeEqual(left: string, right: string): boolean {
  const leftBytes = encoder.encode(left);
  const rightBytes = encoder.encode(right);
  const length = Math.max(leftBytes.length, rightBytes.length);
  let difference = leftBytes.length ^ rightBytes.length;

  for (let index = 0; index < length; index += 1) {
    difference |= (leftBytes[index] ?? 0) ^ (rightBytes[index] ?? 0);
  }
  return difference === 0;
}

/** Authorization 헤더가 설정된 Bearer secret과 일치하는지 확인한다. */
export function isAuthorized(authorization: string | undefined, expectedToken: string): boolean {
  const prefix = "Bearer ";
  if (!authorization?.startsWith(prefix)) {
    return false;
  }
  return constantTimeEqual(authorization.slice(prefix.length), expectedToken);
}
