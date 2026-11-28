/**
 * 4-state ScrollFollowMachine (VS Code Chat + OpenCode scroll discipline).
 *
 * States:
 * - FOLLOWING: pinned to bottom; incoming content auto-scrolls smoothly.
 * - USER_PAUSED: user scrolled upward; incoming content never steals focus.
 * - NEW_CONTENT_BELOW: paused AND new streaming chunks arrived below the fold.
 * - JUMPING_TO_BOTTOM: programmatic jump in flight; settles to FOLLOWING at bottom.
 */

export type ScrollFollowState =
  | "FOLLOWING"
  | "USER_PAUSED"
  | "NEW_CONTENT_BELOW"
  | "JUMPING_TO_BOTTOM";

export type ScrollFollowEvent =
  | { type: "USER_SCROLL_UP" }
  | { type: "REACHED_BOTTOM" }
  | { type: "CONTENT_APPENDED" }
  | { type: "JUMP_REQUESTED" };

export class ScrollFollowMachine {
  private _state: ScrollFollowState;

  constructor(initial: ScrollFollowState = "FOLLOWING") {
    this._state = initial;
  }

  get state(): ScrollFollowState {
    return this._state;
  }

  get shouldAutoScroll(): boolean {
    return this._state === "FOLLOWING" || this._state === "JUMPING_TO_BOTTOM";
  }

  get showJumpButton(): boolean {
    return this._state === "USER_PAUSED" || this._state === "NEW_CONTENT_BELOW";
  }

  get hasUnreadBelow(): boolean {
    return this._state === "NEW_CONTENT_BELOW";
  }

  transition(event: ScrollFollowEvent): ScrollFollowState {
    switch (event.type) {
      case "USER_SCROLL_UP":
        this._state = "USER_PAUSED";
        return this._state;
      case "REACHED_BOTTOM":
        this._state = "FOLLOWING";
        return this._state;
      case "CONTENT_APPENDED":
        if (this._state === "USER_PAUSED") {
          this._state = "NEW_CONTENT_BELOW";
        }
        return this._state;
      case "JUMP_REQUESTED":
        this._state = "JUMPING_TO_BOTTOM";
        return this._state;
    }
  }
}
