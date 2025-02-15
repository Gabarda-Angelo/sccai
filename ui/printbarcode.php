<!-- printbarcode.php (POS component) -->

<?php
include_once 'connectdb.php';
session_start();
include_once "header.php";

// Validate product ID
if (!isset($_GET['id']) || !is_numeric($_GET['id'])) {
    die("Invalid product ID");
}

$product_id = $_GET['id'];
?>

<!-- Content Wrapper. Contains page content -->
<div class="content-wrapper">
    <!-- Main content -->
    <div class="content">
        <div class="container-fluid">
            <div class="row">
                <div class="col-lg-12">
                    <div class="card card-primary card-outline">
                        <div class="card-header">
                            <h5 class="m-0">Generate Barcode Stickers</h5>
                        </div>
                        <div class="card-body">
                            <form class="form-horizontal" method="post" action="barcode/barcode.php" target="_blank">
                                <?php
                                try {
                                    $stmt = $pdo->prepare("SELECT 
                                        product_id,
                                        product_name,
                                        barcode,
                                        sale_price,
                                        stock,
                                        image
                                        FROM products 
                                        WHERE product_id = :product_id");

                                    $stmt->bindParam(':product_id', $product_id, PDO::PARAM_INT);
                                    $stmt->execute();

                                    if ($stmt->rowCount() == 0) {
                                        echo '<div class="alert alert-danger">Product not found</div>';
                                        exit;
                                    }

                                    $product = $stmt->fetch(PDO::FETCH_OBJ);
                                ?>

                                    <div class="row">
                                        <div class="col-md-6">
                                            <div class="list-group">
                                                <div class="list-group-item list-group-item-info text-center">
                                                    <b>Barcode Information</b>
                                                </div>

                                                <div class="form-group row mt-3">
                                                    <label class="col-sm-4 col-form-label">Product Name:</label>
                                                    <div class="col-sm-8">
                                                        <!-- Add the name attribute "product" so that it gets sent to barcode.php -->
                                                        <input type="text" class="form-control" name="product"
                                                            value="<?= htmlspecialchars($product->product_name) ?>" readonly>
                                                    </div>
                                                </div>

                                                <div class="form-group row">
                                                    <label class="col-sm-4 col-form-label">Barcode:</label>
                                                    <div class="col-sm-8">
                                                        <input type="text" class="form-control"
                                                            name="barcode"
                                                            value="<?= htmlspecialchars($product->barcode) ?>"
                                                            readonly>
                                                    </div>
                                                </div>

                                                <div class="form-group row">
                                                    <label class="col-sm-4 col-form-label">Price:</label>
                                                    <div class="col-sm-8">
                                                        <input type="text" class="form-control"
                                                            name="price"
                                                            value="<?= number_format($product->sale_price, 2) ?>"
                                                            readonly>
                                                    </div>
                                                </div>

                                                <div class="form-group row">
                                                    <label class="col-sm-4 col-form-label">Current Stock:</label>
                                                    <div class="col-sm-8">
                                                        <input type="text" class="form-control"
                                                            value="<?= $product->stock ?>"
                                                            readonly>
                                                    </div>
                                                </div>

                                                <div class="form-group row">
                                                    <label class="col-sm-4 col-form-label">Number of Barcodes:</label>
                                                    <div class="col-sm-8">
                                                        <input type="number"
                                                            class="form-control"
                                                            name="print_qty"
                                                            min="1"
                                                            max="100"
                                                            value="1"
                                                            required>
                                                    </div>
                                                </div>

                                                <div class="form-group row">
                                                    <div class="col-sm-8 offset-sm-4">
                                                        <button type="submit" class="btn btn-primary btn-lg">
                                                            <i class="fas fa-barcode"></i> Generate Barcodes
                                                        </button>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>

                                        <div class="col-md-6">
                                            <div class="list-group">
                                                <div class="list-group-item list-group-item-info text-center">
                                                    <b>Product Image</b>
                                                </div>
                                                <div class="text-center mt-3">
                                                    <?php if (!empty($product->image)): ?>
                                                        <img src="productimages/<?= htmlspecialchars($product->image) ?>"
                                                            class="img-fluid rounded"
                                                            alt="<?= htmlspecialchars($product->product_name) ?>"
                                                            style="max-height: 300px;">
                                                    <?php else: ?>
                                                        <div class="alert alert-warning">No image available</div>
                                                    <?php endif; ?>
                                                </div>
                                            </div>
                                        </div>
                                    </div>

                                <?php
                                } catch (PDOException $e) {
                                    echo '<div class="alert alert-danger">Database Error: '
                                        . htmlspecialchars($e->getMessage()) . '</div>';
                                }
                                ?>
                            </form>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<?php include_once "footer.php"; ?>