# 공방 AI 비서 iOS 목업

공방 AI 비서 사장님용 대시보드를 SwiftUI로 옮긴 화면 골격입니다. 탭 바와 내비게이션 바, 화면 배치를 [Figma 파일](https://www.figma.com/design/nUn7ayeiKAVljMiPvwQQV3/Untitled)대로 짰습니다. 데이터는 Figma 프레임에서 옮긴 고정 샘플이고 업무 로직, 서버, AI는 아직 붙이지 않았습니다. 버튼은 눌러도 아직 아무 동작이 없는 껍데기입니다. Swift Package나 CocoaPods 같은 외부 의존성은 하나도 없습니다.

## 스크린샷

| 오늘 | 캘린더 | 운영 | 예약 관리 |
|---|---|---|---|
| <img src="docs/screenshots/today.png" alt="오늘 탭 화면" width="200"> | <img src="docs/screenshots/calendar.png" alt="캘린더 탭 월간 화면" width="200"> | <img src="docs/screenshots/operations.png" alt="운영 탭 전체 현황 화면" width="200"> | <img src="docs/screenshots/bookings.png" alt="예약 관리 화면" width="200"> |

| iPad | 다크 모드 |
|---|---|
| <img src="docs/screenshots/ipad.png" alt="iPad 세로 화면, 위쪽 탭 막대" width="400"> | <img src="docs/screenshots/dark.png" alt="다크 모드 화면" width="200"> |

## 목차

- [화면 구성](#화면-구성)
- [준비물](#준비물)
- [시뮬레이터에서 실행하기](#시뮬레이터에서-실행하기)
- [시뮬레이터 사용 팁](#시뮬레이터-사용-팁)
- [실제 iPhone에서 실행하기 (검증하지 않음)](#실제-iphone에서-실행하기-검증하지-않음)
- [테스트 실행하기](#테스트-실행하기)
- [명령줄로 빌드·테스트하기](#명령줄로-빌드테스트하기)
- [문제 해결](#문제-해결)
- [프로젝트 구조](#프로젝트-구조)
- [Figma 화면과 코드 대응표](#figma-화면과-코드-대응표)
- [사용한 iOS 기본 구성 요소](#사용한-ios-기본-구성-요소)
- [아직 넣지 않은 것](#아직-넣지-않은-것)

## 화면 구성

앱 아래쪽 탭은 네 개입니다.

| 탭 | SF Symbol | 내용 |
|---|---|---|
| 오늘 | house | 큰 제목 "사장님, 좋은 아침이에요", 날짜 부제, 숫자 3개, 오늘 할 일 / SNS·스토어 / 배송 / AI 추천 세그먼트, 그룹 목록 |
| 캘린더 | calendar | 월간/주간 전환, 시스템 월 달력(UICalendarView), 선택한 날의 일정 목록 |
| 운영 | square.grid.2x2 | 75% 링, 숫자 4개, 전월 대비 수치, "먼저 확인해주세요", "전체 업무 관리" 목록 |
| 더보기 | ellipsis | 설정 화면 같은 목록. 항목을 누르면 빈 화면이 열립니다 |

오늘 탭에만 탭 바 위로 "AI에게 물어보세요" 막대가 붙습니다. 이 막대를 누르면 비서 시트가 올라옵니다. 캘린더의 점 색은 일정 종류를 나타냅니다. 예약은 파랑, 주문은 주황, 배송은 초록, 할 일은 보라입니다.

운영 탭의 "전체 업무 관리"에서는 예약 관리, 주문 관리, 배송 관리, SNS·스토어 관리 화면으로 넘어갑니다. 네 화면 모두 검색창과 상태 필터, 카드 목록을 갖췄습니다. 더보기 탭은 아직 Figma 프레임이 없어서 임시로 만든 화면입니다.

iPad에서는 탭이 화면 위쪽 막대로 올라갑니다. 다크 모드에서는 시스템 색을 그대로 씁니다.

## 준비물

직접 확인한 환경은 아래 한 가지뿐입니다.

| 항목 | 확인한 값 |
|---|---|
| Mac | Apple silicon, macOS 27.2 |
| Xcode | 27.2 (build 27B52) |
| 시뮬레이터 | iOS 27.2, iPhone 17과 iPad Pro 11-inch (M5) |

앱의 배포 대상은 iOS 26.1입니다. 그래서 iOS SDK 26.1 이상을 담은 Xcode라면 빌드할 수 있어야 합니다. 다만 실제로 시험한 버전은 Xcode 27.2뿐입니다.

## 시뮬레이터에서 실행하기

Xcode를 처음 여는 분도 아래 순서를 그대로 따라 하면 됩니다.

1. Mac App Store에서 Xcode를 설치합니다. developer.apple.com/download에서 받아도 됩니다.
2. Xcode를 한 번 실행합니다. 추가 구성 요소를 설치하겠느냐고 물으면 설치를 끝까지 진행합니다.
3. iOS 시뮬레이터 런타임이 없다면 메뉴에서 **Xcode > Settings… > Components**를 엽니다. 목록에서 iOS 27.x 시뮬레이터를 내려받습니다.
4. 터미널을 열고 저장소를 받은 뒤 프로젝트를 엽니다.

   ```bash
   git clone https://github.com/stevenahhh/gb-ios.git
   cd gb-ios
   open GongbangAssistant.xcodeproj
   ```

   `gb-ios` 폴더 안에서 아래 명령을 써도 프로젝트가 열립니다.

   ```bash
   xed .
   ```

5. Xcode 창 맨 위 도구 막대를 봅니다. 스킴은 **GongbangAssistant**로 고르고 실행 대상은 **iPhone 17 (iOS 27.2)**로 고릅니다.
6. **⌘R**을 누르거나 도구 막대의 **▶** 버튼을 누릅니다. Simulator가 열리고 앱이 오늘 탭에서 시작합니다.
7. 실행을 멈출 때는 **⌘.**을 누릅니다.

### SwiftUI 미리보기

화면 파일에는 모두 `#Preview`를 넣어 두었습니다. 아무 뷰 파일이나 연 다음 **Editor > Canvas**(⌥⌘↩)를 켜면 시뮬레이터 없이도 화면이 바로 뜹니다.

## 시뮬레이터 사용 팁

| 하고 싶은 일 | 방법 |
|---|---|
| 다크 모드 전환 | Features > Toggle Appearance (⇧⌘A) |
| 화면 회전 | ⌘← / ⌘→ |
| 스크린샷 저장 | ⌘S |
| 홈 화면으로 | ⇧⌘H |
| 글자 크기 바꾸기 | Xcode 디버그 막대의 Environment Overrides 버튼(Dynamic Type), 또는 시뮬레이터 안 Settings 앱 > Accessibility > Display & Text Size > Larger Text |
| iPad 화면 보기 | 실행 대상을 "iPad Pro 11-inch (M5)"로 바꾸고 다시 실행 |

## 실제 iPhone에서 실행하기 (검증하지 않음)

> 이 절의 절차는 실제 기기에서 시험하지 않았습니다. 작업하는 동안 쓸 수 있는 iPhone이 없었기 때문입니다. 순서대로 해도 막히는 곳이 있을 수 있습니다.

Apple Account가 있어야 합니다. 무료 Personal Team으로도 앱에 서명할 수 있습니다.

1. **Xcode > Settings… > Accounts**에서 Apple Account를 추가합니다.
2. 프로젝트 내비게이터에서 GongbangAssistant 프로젝트를 고른 뒤 target GongbangAssistant > **Signing & Capabilities**로 갑니다. **Team**에서 본인 팀을 고릅니다.
3. Bundle Identifier `com.stevenahhh.GongbangAssistant`를 겹치지 않는 값으로 바꿉니다. 예를 들어 `com.<yourname>.GongbangAssistant`처럼 씁니다. 기기에서 테스트도 돌릴 생각이면 UI 테스트 타깃의 `com.stevenahhh.GongbangAssistantUITests`도 바꿔 줍니다.
4. iPhone을 케이블로 Mac에 연결하고 iPhone 화면에서 **Trust**를 누릅니다. iPhone은 iOS 26.1 이상이어야 합니다.
5. iPhone에서 개발자 모드를 켭니다. Settings > Privacy & Security > Developer Mode를 켜고 재시동한 뒤 확인을 누릅니다.
6. Xcode 실행 대상을 연결한 iPhone으로 바꾸고 **⌘R**을 누릅니다.
7. 무료 계정이면 첫 실행이 신뢰하지 않은 개발자라는 이유로 막힐 수 있습니다. 그때는 iPhone의 Settings > General > VPN & Device Management에서 개발자 인증서를 신뢰로 바꿉니다.

## 테스트 실행하기

Xcode에서 **Product > Test**(⌘U)를 누르면 GongbangAssistantUITests가 돕니다.

| 테스트 클래스 | 테스트 | 확인하는 내용 |
|---|---|---|
| TabNavigationUITests | testEveryTabShowsItsNavigationTitle | 탭을 모두 눌러 각 탭의 제목을 확인 |
| TabNavigationUITests | testOperationsPushesAreaScreenAndGoesBack | 운영 > 예약 관리로 들어갔다가 돌아오기 |
| TabNavigationUITests | testAssistantAccessoryBelongsToTodayTab | AI 막대가 오늘 탭에만 보이고 비서 시트를 여는지 |
| ScreenshotTourUITests | testCaptureEveryScreen | 모든 화면을 돌며 스크린샷을 테스트 첨부물로 저장 |

결과는 Test navigator(⌘6)에 뜹니다. 스크린샷은 Report navigator(⌘9)에서 해당 실행 아래에 있습니다.

## 명령줄로 빌드·테스트하기

아래 명령은 [준비물](#준비물)의 환경에서 모두 실행해 봤습니다. 저장소 최상위 폴더에서 실행합니다.

먼저 Xcode 버전을 확인합니다.

```bash
xcodebuild -version
```

여기서 다음 오류가 나면 명령줄 도구가 Xcode 대신 Command Line Tools를 가리키는 것입니다.

```
xcode-select: error: tool 'xcodebuild' requires Xcode, but active developer directory '/Library/Developer/CommandLineTools' is a command line tools instance
```

아래 명령을 한 번 실행해 Xcode로 바꿉니다.

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

시스템 설정을 건드리기 싫다면 명령마다 앞에 `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`를 붙여도 됩니다.

스킴 목록과 쓸 수 있는 시뮬레이터를 확인합니다.

```bash
xcodebuild -list -project GongbangAssistant.xcodeproj
xcrun simctl list devices available
```

다음 명령으로 빌드합니다.

```bash
xcodebuild -project GongbangAssistant.xcodeproj -scheme GongbangAssistant -destination 'platform=iOS Simulator,name=iPhone 17,OS=27.2' -derivedDataPath build/DerivedData build
```

빌드가 끝나면 앱을 시뮬레이터에 설치해 실행해 봅니다.

```bash
xcrun simctl boot "iPhone 17"
open -a Simulator
xcrun simctl install booted build/DerivedData/Build/Products/Debug-iphonesimulator/GongbangAssistant.app
xcrun simctl launch booted com.stevenahhh.GongbangAssistant
```

테스트를 돌려 결과 번들을 만들고 스크린샷을 꺼냅니다.

```bash
xcodebuild test -project GongbangAssistant.xcodeproj -scheme GongbangAssistant -destination 'platform=iOS Simulator,name=iPhone 17,OS=27.2' -derivedDataPath build/DerivedData -resultBundlePath build/TestResults.xcresult
xcrun xcresulttool export attachments --path build/TestResults.xcresult --output-path build/screenshots
```

런타임이 여러 개 깔려 있으면 같은 이름의 기기가 둘 이상 생깁니다. 이럴 때는 위처럼 `OS=27.2`를 붙이거나 `simctl list`에서 찾은 `id=<UDID>`를 씁니다. `build/` 폴더는 `.gitignore`에 들어 있어 커밋에 섞이지 않습니다.

## 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| "Unable to find a destination matching the provided destination specifier" | 그 시뮬레이터나 런타임이 설치돼 있지 않음 | `xcrun simctl list devices available`로 확인한 뒤 Settings > Components에서 런타임을 설치하거나 다른 기기 이름을 고릅니다 |
| "Signing for "GongbangAssistant" requires a development team" | 실제 기기로 빌드할 때만 생김 | [실제 iPhone](#실제-iphone에서-실행하기-검증하지-않음) 절의 2단계대로 Team을 지정합니다 |
| Xcode 버전을 바꾼 뒤 이상한 빌드 오류 | 이전 빌드 산출물이 남아 있음 | Product > Clean Build Folder(⇧⌘K)를 누르거나 `~/Library/Developer/Xcode/DerivedData/GongbangAssistant-*`를 지웁니다 |
| VS Code나 Cursor에 "No such module 'UIKit'" 또는 "No such module 'XCTest'" | 편집기의 Swift 언어 서버가 Command Line Tools를 씀 | Xcode나 xcodebuild로 빌드합니다 |
| 기기 언어를 바꿔도 화면이 한국어 | 원래 그렇게 만듦. 달력 로케일은 ko_KR로 고정 | 고칠 것 없음 |

## 프로젝트 구조

```
GongbangAssistant.xcodeproj        프로젝트, 공유 스킴
GongbangAssistant/
├── GongbangAssistantApp.swift     앱 진입점
├── RootTabView.swift              탭 바, AI 막대, 시트
├── Today/TodayView.swift
├── Calendar/
│   ├── CalendarScreen.swift
│   └── MonthCalendarView.swift    UICalendarView 래퍼
├── Operations/
│   ├── OperationsView.swift
│   └── OperationAreaView.swift
├── More/MoreView.swift
├── Assistant/AssistantViews.swift AI 막대와 비서 시트
├── Shared/
│   ├── Components.swift           숫자 줄, 행, 카드, 배지
│   └── SampleData.swift           샘플 데이터
└── Assets.xcassets                AccentColor, 임시 AppIcon
GongbangAssistantUITests/
├── TabNavigationUITests.swift
└── ScreenshotTourUITests.swift
docs/screenshots/                  README 이미지
```

## Figma 화면과 코드 대응표

| Figma 프레임 | 노드 | 코드 |
|---|---|---|
| 메인화면-오늘할 일 / SNS 스토어 / 배송 / AI 추천 | 1005:34, 1005:107, 1007:92, 1053:241, 1007:128 | `Today/TodayView.swift` |
| 캘린더-월간 / 주간 | 1013:68, 1013:182 | `Calendar/` |
| 운영-전체 현황 | 1054:394 | `Operations/OperationsView.swift` |
| 운영-예약/주문/배송/SNS·스토어 관리 | 1016:331, 1016:570, 1016:809, 1016:1048 | `Operations/OperationAreaView.swift` |
| 하단 메뉴 + AI Chat Input | | `RootTabView.swift`, `Assistant/AssistantViews.swift` |
| 더보기 | 프레임 없음 | `More/MoreView.swift` |

## 사용한 iOS 기본 구성 요소

화면은 직접 그린 컴포넌트 대신 시스템 기본 요소로 짰습니다.

- `TabView`와 `Tab`, `.tabViewStyle(.sidebarAdaptable)`, `.tabBarMinimizeBehavior(.onScrollDown)`, `.tabViewBottomAccessory`
- 탭마다 `NavigationStack`을 두고 `navigationTitle`과 `navigationSubtitle`을 씀
- `UICalendarView`, `Gauge`, `.searchable`, `.buttonStyle(.glassProminent)`
- SF Symbols, 시스템 색, Dynamic Type 글꼴 스타일

AccentColor는 라이트 모드에서 #18181B, 다크 모드에서 #FAFAFA입니다. Figma의 검은 버튼 색에 맞춘 값입니다.

## 아직 넣지 않은 것

- 업무 로직
- 데이터 저장
- 서버 호출과 AI 호출
- 실제로 걸러 주는 검색
- 더보기의 상세 화면
- 앱 아이콘 그림
