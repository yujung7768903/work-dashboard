// 케밥 메뉴의 항목 버튼. 메뉴를 연 줄의 클릭으로 번지지 않게 막는다
export function menuItem(label, onClick) {
  const button = document.createElement("button");
  button.textContent = label;
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  return button;
}
