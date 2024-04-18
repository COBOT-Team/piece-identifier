import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from std_msgs.msg import String
import cv2
from PIL import Image as PILImage
import numpy as np
from yolomodel import YOLOModel
from chess_msgs.msg import FullFEN, GameConfig, ClockButtons
import chess

WHITE = 0
BLACK = 1


def get_piece_name(board, x, y):
    # Convert x and y (1-based index) into a square index (0-based index)
    square = chess.square(7 - y, 7 - x)

    # Get the piece at the given square
    piece = board.piece_at(square)

    if piece:
        # Determine the yor of the piece
        color = "white" if piece.color == chess.WHITE else "black"

        # Determine the type of the piece
        piece_type = {
            chess.PAWN: "pawn",
            chess.KNIGHT: "knight",
            chess.BISHOP: "bishop",
            chess.ROOK: "rook",
            chess.QUEEN: "queen",
            chess.KING: "king",
        }.get(piece.piece_type, "Unknown")

        return f"{piece_type}-{color}"
    else:
        return "empty"


def check_probability(board, inference_matrix):
    final_prob = 1

    for y in range(8):
        for x in range(8):
            board_label = get_piece_name(board, x, y)

            final_prob *= inference_matrix[y][x][board_label]

    return final_prob


class PieceIdentifier(Node):
    def __init__(self):
        super().__init__("piece_identifier")
        
        self.declare_parameter(
            "initial_game_state",
            chess.STARTING_FEN,
            ParameterDescriptor(description="FEN string describing the initial game state"),
        )

        self.model = YOLOModel("cobot_best.pt")
        self.br = CvBridge()

        self.last_img = None
        self.last_depth_img = None
        self.board = chess.Board(self.get_parameter('initial_game_state').value)

        # Subscriptions
        self.board_img_sub = self.create_subscription(
            Image, "chessboard/image_raw", self.board_img_cb, 10
        )
        # self.depth_img_sub = self.create_subscription(
        #     Image, "kinect2/depth/image_raw", self.color_img_cb, 10
        # )
        self.restart_game_sub = self.create_subscription(
            GameConfig, "chess/restart_game", self.restart_game_cb, 10
        )
        self.clock_btn_sub = self.create_subscription(ClockButtons, "chess/clock_buttons", self.clock_button, 10)

        # Publishers
        self.game_state_pub = self.create_publisher(
            FullFEN,
            "chess/game_state",
            10,
        )
        self.image_publisher = self.create_publisher(Image, "/chessboard/annotated/image_raw", 10)

        self.game_state_pub.publish(FullFEN(fen=self.board.fen()))
    
        self.my_turn = False
    
    def restart_game(self, _):
        self.board = chess.Board(self.get_parameter('initial_game_state').value)

    def clock_button(self, _):
        self.my_turn = True

    def process_image(self, data):
        # if not self.my_turn:
        #     # Wait
        #     return
        print("callback")
        # Convert ROS Image message to OpenCV image
        current_frame = self.br.imgmsg_to_cv2(data)

        # Convert OpenCV image to Pillow Image
        pil_image = PILImage.fromarray(cv2.cvtColor(current_frame, cv2.COLOR_BGR2RGB))

        # Send to yolo model
        preview_image, inference_matrix = self.model.crop_and_run(pil_image)

        # Convert Pillow image back to OpenCV image
        processed_image = np.array(preview_image)

        # Convert back to ROS Image message and publish
        self.image_publisher.publish(self.br.cv2_to_imgmsg(processed_image, "bgr8"))

        # str_msg = String()
        # str_msg.data = str(inference_matrix)
        # self.matrix_publisher.publish(str_msg)

        if not self.my_turn:
            # Preview image is fine for now, we don't need to progress further. 
            return
        
        # Alright now we need to use the inference matrix to guess at the next state of the board.
        possible_boards = [] # Keeps track of a tuple containing (probability, and board)

        for move in self._board.legal_moves:
            new_board = self._board.copy()

            new_board.push(move)

            probability = check_probability(new_board, inference_matrix)

            possible_boards.append((probability, new_board))
        
        max_tuple = max(possible_boards, key=lambda x: x[0])

        self.board = max_tuple[1]

        self.game_state_pub.publish(FullFEN(fen=self.board.fen()))



def main(args=None):
    rclpy.init(args=args)
    image_processor = PieceIdentifier()
    rclpy.spin(image_processor)
    # Cleanup
    image_processor.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
