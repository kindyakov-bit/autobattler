Ты опытный Python-разработчик. Файл C:\AI\OpenCode Projects\autobattler\ui\game_ui.py, метод run().

Нужно изменить метод run() так, чтобы переходы между фазами происходили по нажатию клавиши или клику мыши, а не по time.sleep().

Сейчас:
- draft: time.sleep(1) -> round_title
- round_title: time.sleep(1) -> battle
- round_end: time.sleep(2) -> draft или done

Нужно заменить на ожидание ввода (клавиша или мышь) перед каждым переходом.

Добавь метод wait_for_input(self) который:
- очищает очередь pygame.event.get()
- в цикле ждёт pygame.KEYDOWN или pygame.MOUSEBUTTONDOWN или pygame.QUIT
- при QUIT -> self.running = False, возвращает False
- при KEYDOWN или MOUSEBUTTONDOWN -> возвращает True

В run():
- draft: замени time.sleep(1) на вызов wait_for_input(), перед этим нарисуй подсказку "Нажмите любую клавишу или кликните мышью..."
- round_title: замени time.sleep(1) на вызов wait_for_input(), перед этим нарисуй подсказку
- round_end: замени time.sleep(2) на вызов wait_for_input(), перед этим нарисуй подсказку

Верни только Python-скрипт patch.py, который читает game_ui.py, делает string.replace для каждого изменения, и сохраняет файл. Без markdown, без лишнего текста.
