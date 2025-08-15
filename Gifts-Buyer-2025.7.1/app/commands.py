import asyncio
from typing import Dict, Any, List, Union

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.handlers import MessageHandler

from app.notifications import send_message
from app.utils.logger import info, warn, error
from data.config import config, t


class CommandHandler:
    def __init__(self, app: Client):
        self.app = app
        self.active_user_sessions: Dict[int, Dict[str, Any]] = {}
        self.app.add_handler(MessageHandler(self.handle_private_message, filters.text & filters.private & self.is_authorized_user))
        self.app.add_handler(MessageHandler(self.handle_channel_message, filters.text & filters.channel & self.is_authorized_channel))

    def is_authorized_user(self, _, message: Message) -> bool:
        # Проверяем, является ли отправитель сообщения одним из получателей в GIFT_RANGES
        # или если CHANNEL_ID не установлен, то любой пользователь может быть авторизован
        if not config.CHANNEL_ID:
            return True # Если CHANNEL_ID не установлен, разрешаем всем
            
        for r in config.GIFT_RANGES:
            if message.from_user and message.from_user.id in r['recipients']:
                return True
        return False

    def is_authorized_channel(self, _, message: Message) -> bool:
        # Проверяем, что сообщение пришло из настроенного CHANNEL_ID
        return message.chat.id == config.CHANNEL_ID

    async def handle_private_message(self, _, message: Message):
        # Если CHANNEL_ID установлен, игнорируем приватные сообщения от неавторизованных пользователей
        if config.CHANNEL_ID and not self.is_authorized_user(_, message):
            return

        await self._process_command(message)

    async def handle_channel_message(self, _, message: Message):
        # Если CHANNEL_ID установлен, обрабатываем сообщения только из него
        if config.CHANNEL_ID and not self.is_authorized_channel(_, message):
            return

        await self._process_command(message)

    async def _process_command(self, message: Message):
        user_id = message.from_user.id if message.from_user else message.chat.id
        text = message.text.strip()

        if text == "/settings":
            await self.send_settings_menu(message.chat.id)
            self.active_user_sessions[user_id] = {"state": "settings_menu"}
        elif text == "/d":
            await self.send_delete_menu(message.chat.id)
            self.active_user_sessions[user_id] = {"state": "delete_range"}
        elif text.startswith("/d") and len(text) > 2 and text[2:].isdigit():
            await self.delete_range(message.chat.id, int(text[2:]) - 1)
            self.active_user_sessions.pop(user_id, None) # Завершаем сессию
        elif text == "/r":
            await self.send_edit_menu(message.chat.id)
            self.active_user_sessions[user_id] = {"state": "edit_range_select"}
        elif text.startswith("/r") and len(text) > 2 and text[2:].isdigit():
            range_index = int(text[2:]) - 1
            if 0 <= range_index < len(config.GIFT_RANGES):
                await send_message(self.app, t("commands.enter_new_range_format"))
                self.active_user_sessions[user_id] = {"state": "edit_range_input", "index": range_index}
            else:
                await send_message(self.app, t("commands.invalid_range_number"))
                self.active_user_sessions.pop(user_id, None)
        elif user_id in self.active_user_sessions and self.active_user_sessions[user_id]["state"] == "edit_range_input":
            await self.edit_range(message.chat.id, self.active_user_sessions[user_id]["index"], text)
            self.active_user_sessions.pop(user_id, None) # Завершаем сессию
        elif text == "/a":
            await send_message(self.app, t("commands.enter_new_range_format"))
            self.active_user_sessions[user_id] = {"state": "add_range"}
        elif user_id in self.active_user_sessions and self.active_user_sessions[user_id]["state"] == "add_range":
            await self.add_range(message.chat.id, text)
            self.active_user_sessions.pop(user_id, None) # Завершаем сессию
        elif text == "/l":
            # List available gifts dynamically with filtering and formatting
            from app.utils.detector import GiftDetector
            current_gifts, gift_ids = await GiftDetector.fetch_current_gifts(self.app)
            if not current_gifts:
                await send_message(self.app, "Список подарков пуст.")
            else:
                available_gifts = []
                sold_out_gifts = []
                for gift_id, gift_data in current_gifts.items():
                    price = gift_data.get("price", "N/A")
                    emoji = gift_data.get("sticker", {}).get("emoji", "")
                    total_amount = gift_data.get("total_amount", None)
                    available_amount = gift_data.get("available_amount", None)
                    upgrade_price = gift_data.get("upgrade_price", None)
                    sold_out = gift_data.get("is_sold_out", False)
                    sold_out_text = "🔴 SOLD OUT" if sold_out else "🟢 Available"
                    supply_text = ""
                    if total_amount is not None and available_amount is not None:
                        supply_text = f"💎 Supply: {available_amount} • {sold_out_text}"
                    upgrade_text = f"⬆️ Upgrade: {upgrade_price} ⭐️" if upgrade_price else ""
                    gift_str = f"{emoji} [{gift_id}] • {price} ⭐️"
                    if sold_out:
                        sold_out_gifts.append(f"{gift_str}\n🔴 SOLD OUT\n{supply_text}\n{upgrade_text}")
                    else:
                        available_gifts.append(gift_str)
                import logging
                logger = logging.getLogger("gifts_buyer")
                logger.info("Список всех подарков:")
                for gift_id, gift_data in current_gifts.items():
                    logger.info(f"ID: {gift_id} | Data: {gift_data}")
                # Remove sending stickers to avoid DOCUMENT_INVALID and FLOOD_WAIT errors
                # Prepare and send text messages with gift list including emojis
                message_lines = ["Список доступных подарков:"]
                for idx, gift in enumerate(available_gifts, start=1):
                    # Remove emoji from gift string, keep only text
                    gift_text = gift.split(' ', 1)[1] if ' ' in gift else gift
                    message_lines.append(f"{idx}. {gift_text}")
                for idx, gift in enumerate(sold_out_gifts, start=len(available_gifts) + 1):
                    message_lines.append(f"{idx}. {gift}")
                # Split messages into chunks of 10 gifts to avoid message length limits
                chunk_size = 25
                for i in range(0, len(message_lines), chunk_size):
                    chunk = message_lines[i:i+chunk_size]
                    await send_message(self.app, "\n\n".join(chunk))
        elif text == "/g":
            # Start gift purchase session
            await send_message(self.app, "Введите ID подарка. Список подарков: /l")
            self.active_user_sessions[user_id] = {"state": "awaiting_gift_id"}
        elif user_id in self.active_user_sessions:
            state = self.active_user_sessions[user_id]["state"]
            if state == "awaiting_gift_id":
                # Проверяем, что введенный ID подарка есть в config.GIFT_RANGES по полю "id"
                gift_ids = [r.get("id") for r in config.GIFT_RANGES if "id" in r]
                # Приводим все ID подарков к строкам для сравнения
                gift_ids_str = [str(r.get("id")) for r in config.GIFT_RANGES if "id" in r]
                if text in gift_ids_str:
                    self.active_user_sessions[user_id]["gift_id"] = text
                    await send_message(self.app, "Введите количество:")
                    self.active_user_sessions[user_id]["state"] = "awaiting_quantity"
                else:
                    await send_message(self.app, "Неверный ID подарка. Попробуйте снова или введите /l для списка подарков.")
            elif state == "awaiting_quantity":
                if text.isdigit() and int(text) > 0:
                    self.active_user_sessions[user_id]["quantity"] = int(text)
                    await send_message(self.app, "Введите юзернейм получателя (без @):")
                    self.active_user_sessions[user_id]["state"] = "awaiting_recipient"
                else:
                    await send_message(self.app, "Неверное количество. Попробуйте снова.")
            elif state == "awaiting_recipient":
                recipient = text.strip()
                if recipient:
                    gift_id_str = self.active_user_sessions[user_id]["gift_id"]
                    # Ищем gift_range по ID подарка
                    gift_range = next((r for r in config.GIFT_RANGES if str(r.get("id")) == gift_id_str), None)
                    gift_id = gift_range.get("id", None) if gift_range else gift_id_str
                    quantity = self.active_user_sessions[user_id]["quantity"]
                    # Call buy_gift function to purchase the gift
                    from app.purchase import buy_gift
                    try:
                        await buy_gift(self.app, recipient, gift_id, quantity)
                        await send_message(self.app, f"Подарок успешно куплен для @{recipient}!")
                    except Exception as e:
                        await send_message(self.app, f"Ошибка при покупке подарка: {str(e)}")
                    self.active_user_sessions.pop(user_id, None)
                else:
                    await send_message(self.app, "Юзернейм не может быть пустым. Попробуйте снова.")
        elif user_id in self.active_user_sessions and self.active_user_sessions[user_id]["state"] == "settings_menu":
            if text == "/d":
                await self.send_delete_menu(message.chat.id)
                self.active_user_sessions[user_id]["state"] = "delete_range"
            elif text.startswith("/d") and len(text) > 2 and text[2:].isdigit():
                await self.delete_range(message.chat.id, int(text[2:]) - 1)
                self.active_user_sessions.pop(user_id, None) # Завершаем сессию
            elif text == "/r":
                await self.send_edit_menu(message.chat.id)
                self.active_user_sessions[user_id]["state"] = "edit_range_select"
            elif text.startswith("/r") and len(text) > 2 and text[2:].isdigit():
                range_index = int(text[2:]) - 1
                if 0 <= range_index < len(config.GIFT_RANGES):
                    await send_message(self.app, t("commands.enter_new_range_format"))
                    self.active_user_sessions[user_id] = {"state": "edit_range_input", "index": range_index}
                else:
                    await send_message(self.app, t("commands.invalid_range_number"))
                    self.active_user_sessions.pop(user_id, None)
            elif user_id in self.active_user_sessions and self.active_user_sessions[user_id]["state"] == "edit_range_input":
                await self.edit_range(message.chat.id, self.active_user_sessions[user_id]["index"], text)
                self.active_user_sessions.pop(user_id, None) # Завершаем сессию
            elif text == "/a":
                await send_message(self.app, t("commands.enter_new_range_format"))
                self.active_user_sessions[user_id] = {"state": "add_range"}
            elif user_id in self.active_user_sessions and self.active_user_sessions[user_id]["state"] == "add_range":
                await self.add_range(message.chat.id, text)
                self.active_user_sessions.pop(user_id, None) # Завершаем сессию
            else:
                await send_message(self.app, t("commands.unknown_command"))
                self.active_user_sessions.pop(user_id, None) # Завершаем сессию при неизвестной команде
        else:
            # Если это не команда .settings и нет активной сессии, игнорируем
            pass

    async def send_settings_menu(self, chat_id: Union[int, str]):
        message = t("commands.settings_menu")
        await send_message(self.app, message)

    async def send_delete_menu(self, chat_id: Union[int, str]):
        if not config.GIFT_RANGES:
            await send_message(self.app, t("commands.no_ranges_to_delete"))
            return

        ranges_list = "\n\n".join([
            ">" + "\n>".join([f" Диапазон #{i + 1}"] + [line.lstrip("> ") for line in self._format_range_for_display(r).splitlines()])
            for i, r in enumerate(config.GIFT_RANGES)
        ])
        message = t("commands.delete_menu", ranges_list=ranges_list)
        await send_message(self.app, message)

    async def delete_range(self, chat_id: Union[int, str], index: int):
        if 0 <= index < len(config.GIFT_RANGES):
            deleted_range = config.GIFT_RANGES.pop(index)
            config.save_gift_ranges() # Сохраняем изменения
            await send_message(self.app, t("commands.range_deleted", range_info=self._format_range_for_display(deleted_range)))
            info(f"Диапазон удален: {deleted_range}")
        else:
            await send_message(self.app, t("commands.invalid_range_number"))

    async def send_edit_menu(self, chat_id: Union[int, str]):
        if not config.GIFT_RANGES:
            await send_message(self.app, t("commands.no_ranges_to_edit"))
            return

        ranges_list = "\n\n".join([
            ">" + "\n>".join([f" Диапазон #{i + 1}"] + [line.lstrip("> ") for line in self._format_range_for_display(r).splitlines()])
            for i, r in enumerate(config.GIFT_RANGES)
        ])
        message = t("commands.edit_menu", ranges_list=ranges_list)
        await send_message(self.app, message)

    async def edit_range(self, chat_id: Union[int, str], index: int, new_range_str: str):
        parsed_range = config._parse_single_range(new_range_str)
        if parsed_range:
            config.GIFT_RANGES[index] = parsed_range
            config.save_gift_ranges() # Сохраняем изменения
            await send_message(self.app, t("commands.range_edited", range_info=self._format_range_for_display(parsed_range)))
            info(f"Диапазон отредактирован: {parsed_range}")
        else:
            await send_message(self.app, t("commands.invalid_range_format"))

    async def add_range(self, chat_id: Union[int, str], new_range_str: str):
        parsed_range = config._parse_single_range(new_range_str)
        if parsed_range:
            config.GIFT_RANGES.append(parsed_range)
            config.save_gift_ranges() # Сохраняем изменения
            await send_message(self.app, t("commands.range_added", range_info=self._format_range_for_display(parsed_range)))
            info(f"Диапазон добавлен: {parsed_range}")
        else:
            await send_message(self.app, t("commands.invalid_range_format"))

    def _format_range_for_display(self, r: Dict[str, Any]) -> str:
        price_range = f"{r['min_price']}-{r['max_price']}⭐️"
        supply_limit = f"До {r['supply_limit']}" if r['supply_limit'] > 0 else "Без лимита"
        quantity = f"{r['quantity']} шт."
        recipients = ", ".join([f"@{rec}" if isinstance(rec, str) else str(rec) for rec in r['recipients']])
        return f"{price_range}\nСаплай: {supply_limit}\nПолучатель: {recipients}\nПокупать: {quantity}"
