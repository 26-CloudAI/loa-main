{
  "openapi": "3.1.0",
  "info": {
    "title": "AI Arena",
    "description": "AI 봇 배틀로얄 실시간 관전 플랫폼",
    "version": "1.0.0"
  },
  "paths": {
    "/auth/login": {
      "post": {
        "tags": [
          "auth"
        ],
        "summary": "Login",
        "description": "이메일 + 비밀번호로 로그인하고 Mock Token을 발급한다.\n\n요청:\n    { \"email\": \"alice@arena.dev\", \"password\": \"alice1234\" }\n\n응답:\n    {\n        \"access_token\": \"\u003Cmock_token\u003E\",\n        \"token_type\": \"bearer\",\n        \"expires_in\": 3600,\n        \"user\": { ...users 스키마... }\n    }\n\nFirebase 전환 후:\n    - 프론트가 Firebase SDK로 로그인하고 ID Token을 이 엔드포인트로 전달\n    - 서버는 Firebase Admin SDK로 토큰 검증 후 DB Upsert",
        "operationId": "login_auth_login_post",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "additionalProperties": true,
                "type": "object",
                "title": "Body"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/auth/logout": {
      "post": {
        "tags": [
          "auth"
        ],
        "summary": "Logout",
        "description": "로그아웃.\nMock에서는 서버 상태가 없으므로 클라이언트에서 토큰을 삭제하면 된다.\nFirebase 전환 후에도 서버 측 처리는 동일(Firebase 토큰 취소는 선택적).",
        "operationId": "logout_auth_logout_post",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          }
        },
        "security": [
          {
            "HTTPBearer": []
          }
        ]
      }
    },
    "/auth/me": {
      "get": {
        "tags": [
          "auth"
        ],
        "summary": "Get Me",
        "description": "현재 로그인 사용자 프로필 조회.\n\n응답: users 테이블 목표 스키마 그대로",
        "operationId": "get_me_auth_me_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          }
        },
        "security": [
          {
            "HTTPBearer": []
          }
        ]
      }
    },
    "/auth/users": {
      "get": {
        "tags": [
          "auth"
        ],
        "summary": "List Mock Users",
        "description": "Mock 사용자 목록 (개발 편의용).\n비밀번호와 테스트 계정 정보를 확인하기 위한 엔드포인트.\n\nFirebase 전환 후 이 엔드포인트는 삭제한다.",
        "operationId": "list_mock_users_auth_users_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          }
        }
      }
    },
    "/api/games": {
      "get": {
        "summary": "List Games",
        "description": "활성 게임 목록.",
        "operationId": "list_games_api_games_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          }
        }
      },
      "post": {
        "summary": "Create Game",
        "description": "게임을 생성하고 시작한다.\n\nBody:\n{\n    \"bots\": [{\"bot_id\": \"my_bot\", \"code\": \"def action(state): ...\"}],\n    \"tick_interval\": 0.05,\n    \"seed\": 42,\n    \"fill_with_ai\": true,\n    \"min_bots\": 4\n}",
        "operationId": "create_game_api_games_post",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "additionalProperties": true,
                "type": "object",
                "title": "Body"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/games/{game_id}": {
      "get": {
        "summary": "Get Game",
        "description": "게임 정보.",
        "operationId": "get_game_api_games__game_id__get",
        "parameters": [
          {
            "name": "game_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Game Id"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      },
      "delete": {
        "summary": "Stop Game",
        "description": "게임을 강제 종료.",
        "operationId": "stop_game_api_games__game_id__delete",
        "parameters": [
          {
            "name": "game_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Game Id"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/games/{game_id}/result": {
      "get": {
        "summary": "Get Game Result",
        "description": "게임 결과.",
        "operationId": "get_game_result_api_games__game_id__result_get",
        "parameters": [
          {
            "name": "game_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Game Id"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/health": {
      "get": {
        "summary": "Health",
        "operationId": "health_health_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          }
        }
      }
    },
    "/api/bots": {
      "get": {
        "summary": "List My Bots",
        "description": "내 봇 목록을 조회합니다.",
        "operationId": "list_my_bots_api_bots_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          }
        }
      },
      "post": {
        "summary": "Register Bot",
        "description": "새로운 봇 코드를 등록합니다.",
        "operationId": "register_bot_api_bots_post",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/BotCreateRequest"
              }
            }
          },
          "required": true
        },
        "responses": {
          "201": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/bots/{bot_id}": {
      "get": {
        "summary": "Get Bot",
        "description": "특정 봇의 상세 정보를 조회합니다.",
        "operationId": "get_bot_api_bots__bot_id__get",
        "parameters": [
          {
            "name": "bot_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Bot Id"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      },
      "put": {
        "summary": "Update Bot",
        "description": "기존 봇의 코드를 업데이트하고 버전을 증가시킵니다.",
        "operationId": "update_bot_api_bots__bot_id__put",
        "parameters": [
          {
            "name": "bot_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Bot Id"
            }
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/BotUpdateRequest"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      },
      "delete": {
        "summary": "Delete Bot",
        "description": "봇을 삭제합니다.",
        "operationId": "delete_bot_api_bots__bot_id__delete",
        "parameters": [
          {
            "name": "bot_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Bot Id"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "BotCreateRequest": {
        "properties": {
          "name": {
            "type": "string",
            "maxLength": 50,
            "minLength": 1,
            "title": "Name",
            "description": "봇 이름"
          },
          "code": {
            "type": "string",
            "title": "Code",
            "description": "봇 파이썬 코드"
          }
        },
        "type": "object",
        "required": [
          "name",
          "code"
        ],
        "title": "BotCreateRequest"
      },
      "BotUpdateRequest": {
        "properties": {
          "code": {
            "type": "string",
            "title": "Code",
            "description": "업데이트할 봇 파이썬 코드"
          }
        },
        "type": "object",
        "required": [
          "code"
        ],
        "title": "BotUpdateRequest"
      },
      "HTTPValidationError": {
        "properties": {
          "detail": {
            "items": {
              "$ref": "#/components/schemas/ValidationError"
            },
            "type": "array",
            "title": "Detail"
          }
        },
        "type": "object",
        "title": "HTTPValidationError"
      },
      "ValidationError": {
        "properties": {
          "loc": {
            "items": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "integer"
                }
              ]
            },
            "type": "array",
            "title": "Location"
          },
          "msg": {
            "type": "string",
            "title": "Message"
          },
          "type": {
            "type": "string",
            "title": "Error Type"
          },
          "input": {
            "title": "Input"
          },
          "ctx": {
            "type": "object",
            "title": "Context"
          }
        },
        "type": "object",
        "required": [
          "loc",
          "msg",
          "type"
        ],
        "title": "ValidationError"
      }
    },
    "securitySchemes": {
      "HTTPBearer": {
        "type": "http",
        "scheme": "bearer"
      }
    }
  }
}